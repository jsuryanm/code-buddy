import io

from codebuddy.mcp_server import server


class _Stdin(io.StringIO):
    def __init__(self, tty: bool):
        super().__init__()
        self._tty = tty

    def isatty(self) -> bool:
        return self._tty


def _run_main(monkeypatch, tty: bool) -> list[str]:
    calls: list[str] = []
    monkeypatch.setattr(server.mcp, "run", lambda transport: calls.append(transport))
    monkeypatch.setattr("sys.stdin", _Stdin(tty))
    server.main()
    return calls


def test_main_prints_banner_to_stderr_on_a_terminal(monkeypatch, capsys):
    assert _run_main(monkeypatch, tty=True) == ["stdio"]
    out = capsys.readouterr()
    assert out.out == ""
    assert "codebuddy-tools MCP server on stdio" in out.err
    assert "Ctrl+C" in out.err


def test_main_is_silent_when_a_client_pipes_stdin(monkeypatch, capsys):
    assert _run_main(monkeypatch, tty=False) == ["stdio"]
    out = capsys.readouterr()
    assert out.out == "" and out.err == ""
