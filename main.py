from greennode_agentbase import GreenNodeAgentBaseApp, PingStatus, RequestContext

from app.agent import analyze_payload
from app.routes import register_routes

app = GreenNodeAgentBaseApp()
register_routes(app)


@app.entrypoint
def handler(payload: dict, context: RequestContext) -> dict:
    return analyze_payload(payload, session_id=context.session_id)


@app.ping
def health_check() -> PingStatus:
    return PingStatus.HEALTHY


if __name__ == "__main__":
    app.run()
