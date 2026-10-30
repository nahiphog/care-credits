from fastapi import APIRouter


def register(app, service):
    router = APIRouter(tags=['user'])
    router.add_api_route('/api/v1/me', service.me, methods=['GET'])
    router.add_api_route('/api/v1/me', service.change_profile, methods=['PATCH'])
    router.add_api_route('/api/v1/trainings', service.trainings, methods=['GET'])
    router.add_api_route('/api/v1/trainings/{course_id}', service.detail, methods=['GET'])
    router.add_api_route('/api/v1/me/trainings/{course_id}', service.save_record, methods=['PUT'])
    router.add_api_route('/api/v1/me/trainings', service.my_trainings, methods=['GET'])
    router.add_api_route('/api/v1/me/progress', service.progress, methods=['GET'])
    router.add_api_route('/api/v1/me/trainings/{course_id}/history', service.record_history, methods=['GET'])
    router.add_api_route('/api/v1/me/suggestions', service.me_suggestions, methods=['GET'])
    router.add_api_route('/api/v1/me/digest', service.get_digest, methods=['GET'])
    router.add_api_route('/api/v1/me/digest', service.patch_digest, methods=['PATCH'])
    router.add_api_route('/api/v1/me/certificates', service.create_certificate, methods=['POST'], status_code=201)
    router.add_api_route('/api/v1/me/certificates/{certificate_id}', service.download_certificate, methods=['GET'])
    router.add_api_route('/api/v1/me/export/{kind}', service.export, methods=['GET'])
    router.add_api_route('/api/v1/me/audit', service.my_audit, methods=['GET'])
    app.include_router(router)
