from fastapi import APIRouter


def register(app, service):
    router = APIRouter(tags=['admin'])
    router.add_api_route('/api/v1/admin/services', service.services, methods=['GET'])
    router.add_api_route('/api/v1/admin/integrations', service.integrations, methods=['GET'])
    router.add_api_route('/api/v1/admin/digests/run', service.admin_run_digests, methods=['POST'])
    router.add_api_route('/api/v1/admin/audit', service.admin_audit, methods=['GET'])
    router.add_api_route('/api/v1/admin/ingestion-jobs', service.create_job, methods=['POST'], status_code=202)
    router.add_api_route('/api/v1/admin/ingestion-jobs/{job_id}/run', service.run_serverless_job, methods=['POST'])
    router.add_api_route('/api/v1/admin/ingestion-jobs', service.jobs, methods=['GET'])
    router.add_api_route('/api/v1/admin/ingestion-jobs/{job_id}', service.job_detail, methods=['GET'])
    router.add_api_route('/api/v1/admin/ingestion-jobs/{job_id}/retry', service.retry_job, methods=['POST'], status_code=202)
    router.add_api_route('/api/v1/admin/candidates', service.candidates, methods=['GET'])
    router.add_api_route('/api/v1/admin/candidates/{candidate_id}/review', service.review, methods=['POST'])
    router.add_api_route('/api/v1/admin/trainings/{course_id}/cancel', service.cancel_training, methods=['POST'])
    router.add_api_route('/api/v1/admin/scrape-topics', service.scrape_topics, methods=['GET'])
    router.add_api_route('/api/v1/admin/daily-scrape', service.trigger_daily_scrape, methods=['POST'], status_code=202)
    app.include_router(router)
