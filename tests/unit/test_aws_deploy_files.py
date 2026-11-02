"""Static checks of the AWS free-tier deployment (deploy/aws). Nothing here calls AWS or Docker."""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from codebuddy.config import Settings

yaml = pytest.importorskip("yaml")

ROOT = Path(__file__).parents[2]
AWS = ROOT / "deploy" / "aws"
TEMPLATE_TEXT = (AWS / "template.yaml").read_text()
COMPOSE_TEXT = (AWS / "docker-compose.aws.yml").read_text()
CADDY_TEXT = (AWS / "Caddyfile").read_text()
WORKFLOW_TEXT = (ROOT / ".github" / "workflows" / "docker-publish.yml").read_text()
SCRIPTS = sorted((AWS / "scripts").glob("*.sh"))
CLIENT_ONLY = {"CODEBUDDY_API_URL", "CODEBUDDY_API_KEY"}


class CfnLoader(yaml.SafeLoader):
    """SafeLoader that turns CloudFormation short tags (!Sub, !Ref, ...) into long form."""


def _tag(loader, suffix, node):
    name = "Ref" if suffix == "Ref" else f"Fn::{suffix}"
    if isinstance(node, yaml.ScalarNode):
        value = loader.construct_scalar(node)
        if suffix == "GetAtt":
            value = value.split(".", 1)
    elif isinstance(node, yaml.SequenceNode):
        value = loader.construct_sequence(node, deep=True)
    else:
        value = loader.construct_mapping(node, deep=True)
    return {name: value}


CfnLoader.add_multi_constructor("!", _tag)
TEMPLATE = yaml.load(TEMPLATE_TEXT, Loader=CfnLoader)  # noqa: S506 - SafeLoader subclass
COMPOSE = yaml.safe_load(COMPOSE_TEXT)
RESOURCES = TEMPLATE["Resources"]

# Long but realistic values, so the size check is not optimistic.
PLACEHOLDERS = {
    "ImageUri": "ghcr.io/a-fairly-long-github-owner-name/code-buddy:0123456789abcdef",
    "BasicAuthUser": "a" * 32,
    "SsmPrefix": "/code-buddy/production/eu-central-1",
    "DomainName": "tutor.some-long-subdomain.example-domain.com",
    "AWS::Region": "ap-southeast-2",
    "ElasticIp.PublicIp": "255.255.255.255",
    "AWS::StackName": "code-buddy",
    "AWS::AccountId": "123456789012",
    "AWS::Partition": "aws",
}


def render(node, local=None):
    """Evaluate the few intrinsic functions the UserData uses, with placeholder values."""
    local = local or {}
    if isinstance(node, str):
        return node
    if isinstance(node, list):
        return [render(item, local) for item in node]
    (fn, arg), *_ = node.items()
    if fn == "Ref":
        return local.get(arg, PLACEHOLDERS.get(arg, arg))
    if fn == "Fn::GetAtt":
        return PLACEHOLDERS[".".join(arg)]
    if fn == "Fn::If":
        return render(arg[1], local)  # the DomainName branch: the longer one
    if fn == "Fn::Join":
        return arg[0].join(render(arg[1], local))
    if fn == "Fn::Split":
        return render(arg[1], local).split(arg[0])
    if fn == "Fn::Base64":
        return render(arg, local)
    if fn == "Fn::Sub":
        text, extra = (arg, {}) if isinstance(arg, str) else arg
        values = {**PLACEHOLDERS, **{k: render(v, local) for k, v in extra.items()}}
        text = re.sub(r"\$\{(?!!)([^}]+)\}", lambda m: values[m[1]], text)
        return text.replace("${!", "${")
    raise AssertionError(f"unexpected intrinsic {fn}")


USER_DATA = render(RESOURCES["Instance"]["Properties"]["UserData"])


def heredoc(marker: str) -> str:
    match = re.search(rf"<<'{marker}'\n(.*?)^{marker}\n", USER_DATA, re.S | re.M)
    assert match, marker
    return match[1]


def test_template_has_expected_resources_and_parameters():
    types = {r["Type"] for r in RESOURCES.values()}
    assert {
        "AWS::EC2::SecurityGroup",
        "AWS::IAM::Role",
        "AWS::IAM::InstanceProfile",
        "AWS::EC2::EIP",
        "AWS::EC2::EIPAssociation",
        "AWS::EC2::Instance",
    } == types
    params = TEMPLATE["Parameters"]
    assert params["InstanceType"]["AllowedValues"] == ["t3.small", "t3.micro"]
    assert params["InstanceType"]["Default"] == "t3.small"
    assert (params["VolumeSizeGiB"]["MinValue"], params["VolumeSizeGiB"]["MaxValue"]) == (8, 30)
    assert params["ImageUri"]["Default"].startswith("ghcr.io/")
    assert "al2023-ami-kernel-default-x86_64" in params["LatestAmiId"]["Default"]
    assert all("Description" in p for p in params.values())
    assert {"Url", "InstanceId", "PublicIp", "ConnectCommand", "BootstrapLogCommand"} <= set(
        TEMPLATE["Outputs"]
    )
    assert "DeleteCommand" in TEMPLATE["Outputs"]
    assert not any("DeletionPolicy" in r for r in RESOURCES.values())


def test_security_group_opens_only_80_and_443():
    rules = RESOURCES["SecurityGroup"]["Properties"]["SecurityGroupIngress"]
    assert sorted((r["FromPort"], r["ToPort"], r["IpProtocol"]) for r in rules) == [
        (80, 80, "tcp"),
        (443, 443, "tcp"),
    ]


def test_instance_hardening():
    props = RESOURCES["Instance"]["Properties"]
    assert props["MetadataOptions"]["HttpTokens"] == "required"
    assert props["MetadataOptions"]["HttpPutResponseHopLimit"] == 1
    ebs = props["BlockDeviceMappings"][0]["Ebs"]
    assert ebs["Encrypted"] is True and ebs["VolumeType"] == "gp3"
    assert "KeyName" not in props, "no SSH key: access is through Session Manager"
    assert props["IamInstanceProfile"] == {"Ref": "InstanceProfile"}


def test_role_reads_only_its_parameters():
    role = RESOURCES["InstanceRole"]["Properties"]
    assert any("AmazonSSMManagedInstanceCore" in str(a) for a in role["ManagedPolicyArns"])
    statements = role["Policies"][0]["PolicyDocument"]["Statement"]
    ssm = next(s for s in statements if "ssm:GetParametersByPath" in s["Action"])
    assert all("parameter${SsmPrefix}" in r["Fn::Sub"] for r in ssm["Resource"])
    assert not any(a.startswith("ssm:Put") or a == "ssm:*" for a in ssm["Action"])
    kms = next(s for s in statements if s["Action"] == "kms:Decrypt")
    assert "kms:ViaService" in kms["Condition"]["StringEquals"]


def test_user_data_under_16_kb_and_strict():
    assert len(USER_DATA.encode()) < 16000, len(USER_DATA.encode())
    assert USER_DATA.startswith("#!/bin/bash\n")
    assert "set -euo pipefail" in USER_DATA and "trap " in USER_DATA
    assert "/var/log/codebuddy-bootstrap.log" in USER_DATA
    assert re.search(r"COMPOSE_SHA256=[0-9a-f]{64}\n", USER_DATA)
    assert "sha256sum -c" in USER_DATA
    assert "/usr/local/lib/docker/cli-plugins" in USER_DATA
    assert "-o 10001 -g 10001 /opt/codebuddy/logs" in USER_DATA
    assert "${" not in USER_DATA.split("set -o errtrace")[0], "unrendered Fn::Sub variable"


def test_embedded_files_equal_standalone_files():
    hint = "run: uv run python deploy/aws/sync_template.py"
    assert heredoc("COMPOSE") == COMPOSE_TEXT, hint
    assert heredoc("CADDYFILE") == CADDY_TEXT, hint


def test_embedded_env_writer_is_valid_python_and_private():
    source = heredoc("PY")
    compile(source, "codebuddy-env", "exec")
    assert "0o600" in source and "--with-decryption" in source
    prints = [ln for ln in source.splitlines() if "print(" in ln]
    assert prints and not any("values[" in ln or "params[" in ln for ln in prints)


def test_compose_services_and_limits():
    services = COMPOSE["services"]
    assert set(services) == {"caddy", "api", "ui"}
    assert services["api"]["image"].startswith("${IMAGE_URI")
    assert services["caddy"]["image"].startswith("caddy:2.")
    for name, svc in services.items():
        assert svc.get("mem_limit"), name
        assert svc["logging"]["driver"] == "json-file", name
        assert svc["logging"]["options"]["max-size"], name
    for name in ("api", "ui"):
        assert "ports" not in services[name], f"{name} must stay private"
    assert services["caddy"]["ports"] == ["80:80", "443:443"]
    assert services["api"]["environment"]["CODEBUDDY_MEMORY_ENABLED"] == "false"
    assert services["ui"]["environment"]["CODEBUDDY_API_URL"] == "http://api:8000"


def test_compose_codebuddy_names_exist_in_settings():
    fields = {n.lower() for n in Settings.model_fields}
    names = set(re.findall(r"CODEBUDDY_[A-Z0-9_]+", COMPOSE_TEXT + USER_DATA)) - CLIENT_ONLY
    assert names
    for name in names:
        assert name.removeprefix("CODEBUDDY_").lower() in fields, name


def test_caddyfile_auth_streaming_and_headers():
    code = "\n".join(ln for ln in CADDY_TEXT.splitlines() if not ln.lstrip().startswith("#"))
    assert re.search(r"basic_auth \{\s*\{\$BASIC_AUTH_USER\} \{\$BASIC_AUTH_HASH\}", code)
    assert "reverse_proxy ui:8501" in code
    assert code.count("reverse_proxy") == code.count("flush_interval -1") == 1
    assert "8000" not in code, "the API is not published"
    for header in ("Strict-Transport-Security", "X-Content-Type-Options", "X-Frame-Options"):
        assert header in code


def test_no_secret_literals_in_deploy_files():
    pattern = re.compile(
        r"sk-[A-Za-z0-9_-]{8,}|gsk_[A-Za-z0-9]{8,}|pk-lf-[0-9a-f]|sk-lf-[0-9a-f]"
        r"|AKIA[0-9A-Z]{12}|ghp_[A-Za-z0-9]{8,}|github_pat_|\$2[aby]\$\d\d\$"
    )
    files = [p for p in AWS.rglob("*") if p.is_file() and "__pycache__" not in p.parts]
    for path in [*files, ROOT / ".github" / "workflows" / "docker-publish.yml"]:
        assert not pattern.search(path.read_text()), path


def test_scripts_are_strict_and_documented():
    assert {p.name for p in SCRIPTS} >= {
        "put-secrets.sh",
        "make-basic-auth.sh",
        "deploy.sh",
        "update.sh",
        "status.sh",
        "destroy.sh",
        "budget.sh",
    }
    for path in SCRIPTS:
        lines = path.read_text().splitlines()
        assert lines[0] == "#!/usr/bin/env bash", path.name
        assert "set -euo pipefail" in lines[:6], path.name
        assert "usage()" in path.read_text(), path.name
    secrets = (AWS / "scripts" / "put-secrets.sh").read_text()
    assert "read -r -s" in secrets and "SecureString" in secrets
    assert "--value" not in secrets, "values must not travel on the command line"
    assert "read -r -p" in (AWS / "scripts" / "deploy.sh").read_text()


def test_update_command_uses_full_path_everywhere():
    full = "sudo /usr/local/bin/codebuddy-update"
    assert "/usr/local/bin/codebuddy-update <<" in (AWS / "template.yaml").read_text()
    for path in (AWS / "README.md", AWS / "scripts" / "update.sh"):
        text = path.read_text()
        assert full in text, path.name
        assert "sudo codebuddy-" not in text, path.name


def test_publish_workflow():
    workflow = yaml.safe_load(WORKFLOW_TEXT)
    assert workflow["permissions"] == {"contents": "read", "packages": "write"}
    triggers = workflow[True]  # YAML 1.1 reads the key "on" as True
    assert triggers["push"]["branches"] == ["main"] and "workflow_dispatch" in triggers
    steps = workflow["jobs"]["publish"]["steps"]
    build = next(s for s in steps if "build-push" in s.get("uses", ""))
    assert build["with"]["platforms"] == "linux/amd64"
    assert "EXTRAS=--extra ui --extra trace" in build["with"]["build-args"]
    assert "type=gha" in build["with"]["cache-from"]
    assert "ghcr.io/${{ github.repository }}" in WORKFLOW_TEXT
