# 0003. Streamlit for the v1 front end

Status: accepted. Date: 2026-10-29.

## Context
The spec proposed Next.js. The first milestone needs a simple UI to exercise the tutor.

## Decision
Build a thin Streamlit app. All logic stays in the FastAPI service; the UI only renders the SSE
stream and sends messages, code, and the Show-answer action.

## Consequences
Fast to build and test (`AppTest`). Less control over layout, no per-user auth, and Streamlit
reruns the script on each interaction (hence `st.rerun()` after a turn). Because the API contract
is plain SSE, a Next.js UI can replace it without backend changes.
