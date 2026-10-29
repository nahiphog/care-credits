/** Shared Next /api error envelopes for SDD `{error:{code,message,request_id}}`. */

export type ApiErrorBody = {
  error: {
    code: string;
    message: string;
    request_id: string;
  };
};

export const JSON_CONTENT_TYPE = 'application/json; charset=utf-8';

export function envelopeHeaders(requestIdValue: string): Record<string, string> {
  return {
    'Content-Type': JSON_CONTENT_TYPE,
    'X-Request-Id': requestIdValue,
  };
}

export function apiErrorBody(code: string, message: string, requestIdValue: string): ApiErrorBody {
  return {
    error: {
      code,
      message,
      request_id: requestIdValue,
    },
  };
}

export function notFoundBody(requestIdValue: string): ApiErrorBody {
  return apiErrorBody('not_found', 'Not found.', requestIdValue);
}

export function unavailableBody(requestIdValue: string): ApiErrorBody {
  return apiErrorBody('unavailable', 'CareCredits API is unavailable.', requestIdValue);
}
