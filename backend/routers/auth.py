from fastapi import APIRouter


def register(app, service):
    router = APIRouter(tags=['auth'])
    router.add_api_route('/api/v1/auth/register', service.register, methods=['POST'], status_code=201)
    router.add_api_route('/api/v1/auth/login', service.login, methods=['POST'])
    router.add_api_route('/api/v1/auth/oauth/google', service.google_start, methods=['GET'])
    router.add_api_route('/api/v1/auth/oauth/google/callback', service.google_callback, methods=['GET'])
    router.add_api_route('/api/v1/auth/logout', service.logout, methods=['POST'])
    app.include_router(router)
