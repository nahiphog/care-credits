from fastapi import APIRouter


def register(app, service):
    router = APIRouter(tags=['internal'])
    router.add_api_route('/internal/v1/jobs/claim', service.claim, methods=['POST'], dependencies=[service.Depends(service.worker)])
    router.add_api_route('/internal/v1/jobs/{job_id}/heartbeat', service.heartbeat, methods=['POST'], dependencies=[service.Depends(service.worker)])
    router.add_api_route('/internal/v1/jobs/{job_id}/complete', service.complete, methods=['POST'], dependencies=[service.Depends(service.worker)])
    router.add_api_route('/internal/v1/catalogue/connect', service.catalogue_connect, methods=['GET'], dependencies=[service.Depends(service.worker)])
    router.add_api_route('/internal/v1/catalogue/lookup', service.catalogue_lookup, methods=['POST'], dependencies=[service.Depends(service.worker)])
    router.add_api_route('/internal/v1/catalogue/decide', service.catalogue_decide, methods=['POST'], dependencies=[service.Depends(service.worker)])
    router.add_api_route('/internal/v1/catalogue/save', service.catalogue_save, methods=['POST'], dependencies=[service.Depends(service.worker)])
    app.include_router(router)
