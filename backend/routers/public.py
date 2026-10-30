from fastapi import APIRouter


def register(app, service):
    router = APIRouter(tags=['public'])
    router.add_api_route('/health', service.health, methods=['GET'])
    router.add_api_route('/health/live', service.health_live, methods=['GET'])
    router.add_api_route('/health/ready', service.ready, methods=['GET'])
    router.add_api_route('/api/v1/config', service.config, methods=['GET'])
    router.add_api_route('/api/v1/digest/unsubscribe', service.digest_unsubscribe, methods=['GET'])
    router.add_api_route('/api/v1/public/{slug}', service.public_profile, methods=['GET'])
    app.include_router(router)
