'use client';

import { useCallback, useEffect, useRef, useState } from 'react';
import { api, publicWebUrl } from '@/lib/portal';

export type ServiceStatus = {
  backend: string;
  database: string;
  database_owner: string;
  frontend: string;
  paid_scrape_ready?: boolean;
  scraper: {
    status: string;
    reachable: boolean;
    tavily_configured: boolean;
    model_ready: boolean;
  };
};

export type IntegrationFlags = {
  model_id: string | null;
  model_publisher: string | null;
  model_host: string | null;
  model_weights_url: string | null;
  model_license_url: string | null;
  model_identity_provisional?: boolean;
  model_publisher_provisional?: boolean;
  model_host_provisional?: boolean;
  model_weights_provisional?: boolean;
  model_license_provisional?: boolean;
  model_open_weight_confirmed: boolean;
  model_caps_configured: boolean;
  model_caps_provisional?: boolean;
  model_max_input_chars?: number | null;
  model_max_output_tokens?: number | null;
  model_key_configured: boolean;
  typesafe_configured: boolean;
  scraper_token_configured: boolean;
  catalogue_auto_publish_new?: boolean;
};

/** OPEN-03 sample identity. Used when a stale backend omits *provisional flags. */
export const OPEN03_SAMPLE = {
  modelId: 'Qwen/Qwen3-30B-A3B-Instruct-2507',
  publisher: 'Qwen',
  host: 'Nebius Token Factory',
  weightsUrl: 'https://huggingface.co/Qwen/Qwen3-30B-A3B-Instruct-2507',
  licenseUrl: 'https://huggingface.co/Qwen/Qwen3-30B-A3B-Instruct-2507/blob/main/LICENSE',
  inputChars: 12000,
  outputTokens: 4000,
};

export function open03SampleDefault(flag: boolean | undefined, matchesSample: boolean) {
  if (flag === true) return true;
  if (flag === false) return false;
  // Stale backends may omit *provisional flags; match sample values or treat unset identity as provisional.
  return matchesSample;
}

/** When a stale integrations payload omits provisional flags and leaves model_id empty. */
export function identityLooksProvisional(
  flag: boolean | undefined,
  modelId: string | null | undefined,
) {
  if (flag === true) return true;
  if (flag === false) return false;
  return !modelId || modelId === OPEN03_SAMPLE.modelId;
}

export function liveDiscoveryReady(
  services: ServiceStatus | null,
  _integrations: IntegrationFlags | null,
) {
  // Fail closed: curl/API spend gate uses paid_scrape_ready only. A stale backend that
  // omits the flag must not re-enable enqueue from scraper.tavily_configured && model_ready.
  return services?.paid_scrape_ready === true;
}

export function IntegrationStatus({
  className = 'small-note',
  onLiveReady,
}: {
  className?: string;
  onLiveReady?: (ready: boolean, loading: boolean) => void;
}) {
  const [integrations, setIntegrations] = useState<IntegrationFlags | null>(null);
  const [services, setServices] = useState<ServiceStatus | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');
  const readyRef = useRef(onLiveReady);
  readyRef.current = onLiveReady;
  const loadId = useRef(0);

  const load = useCallback(() => {
    const requestId = ++loadId.current;
    setLoading(true);
    readyRef.current?.(false, true);
    setError('');
    Promise.allSettled([api('/admin/services'), api('/admin/integrations')])
      .then(([servicesResult, integrationsResult]) => {
        if (loadId.current !== requestId) return;
        const nextServices = servicesResult.status === 'fulfilled' ? servicesResult.value : null;
        const nextIntegrations = integrationsResult.status === 'fulfilled' ? integrationsResult.value : null;
        setServices(nextServices);
        setIntegrations(nextIntegrations);
        readyRef.current?.(liveDiscoveryReady(nextServices, nextIntegrations), false);
        if (!nextServices && !nextIntegrations) {
          const first =
            (servicesResult.status === 'rejected' && servicesResult.reason) ||
            (integrationsResult.status === 'rejected' && integrationsResult.reason);
          setError(first instanceof Error ? first.message : 'Status could not be loaded.');
        } else if (!nextServices) {
          setError('Three-service readiness is unavailable. Integration flags below are still from this backend.');
        } else if (!nextIntegrations) {
          setError('Integration status could not be loaded.');
        }
      })
      .finally(() => {
        if (loadId.current === requestId) setLoading(false);
      });
  }, []);

  useEffect(() => {
    load();
  }, [load]);

  if (loading) {
    return (
      <p className={className} role="status" aria-busy="true" data-testid="integration-loading">
        Checking service and integration status…
      </p>
    );
  }
  if (!integrations && !services) {
    return error ? (
      <p className={className} role="alert" data-testid="integration-error">
        {error}{' '}
        <button className="text-link" type="button" onClick={load}>
          Retry
        </button>
      </p>
    ) : null;
  }
  const weightsHref = publicWebUrl(integrations?.model_weights_url);
  const licenseHref = publicWebUrl(integrations?.model_license_url);
  const identityProvisional = identityLooksProvisional(
    integrations?.model_identity_provisional,
    integrations?.model_id,
  );
  const publisherProvisional = open03SampleDefault(
    integrations?.model_publisher_provisional,
    (integrations?.model_publisher || '') === OPEN03_SAMPLE.publisher,
  );
  const hostProvisional = open03SampleDefault(
    integrations?.model_host_provisional,
    (integrations?.model_host || '') === OPEN03_SAMPLE.host,
  );
  const capsProvisional = open03SampleDefault(
    integrations?.model_caps_provisional,
    integrations?.model_max_input_chars === OPEN03_SAMPLE.inputChars
      && integrations?.model_max_output_tokens === OPEN03_SAMPLE.outputTokens,
  );
  const weightsProvisional = open03SampleDefault(
    integrations?.model_weights_provisional,
    (integrations?.model_weights_url || '') === OPEN03_SAMPLE.weightsUrl,
  );
  const licenseProvisional = open03SampleDefault(
    integrations?.model_license_provisional,
    (integrations?.model_license_url || '') === OPEN03_SAMPLE.licenseUrl,
  );
  return (
    <>
      {error ? (
        <p className={className} role="alert" data-testid="integration-error">
          {error}{' '}
          <button className="text-link" type="button" onClick={load}>
            Retry
          </button>
        </p>
      ) : null}
      {services ? (
        <p className={className} data-testid="service-status">
          Backend {services.backend} · database {services.database} (owned by {services.database_owner}) · scraper{' '}
          {services.scraper.status}
          {services.scraper.reachable ? '' : ' · scraper unreachable'}
          {services.scraper.tavily_configured ? ' · Tavily configured' : ' · Tavily not configured'}
          {services.scraper.model_ready ? ' · model ready' : ' · model not ready'}
          {liveDiscoveryReady(services, integrations)
            ? ' · live discovery ready'
            : ' · live discovery not ready'}{' '}
          · frontend {services.frontend}.
        </p>
      ) : null}
      {integrations ? (
        <p className={className} data-testid="integration-status">
          Model{' '}
          {integrations.model_id || (identityProvisional ? OPEN03_SAMPLE.modelId : 'not selected')}
          {integrations.model_publisher
            ? ` · ${integrations.model_publisher}${
                !identityProvisional && publisherProvisional ? ' (OPEN-03 sample default)' : ''
              }`
            : identityProvisional
              ? ` · ${OPEN03_SAMPLE.publisher} (OPEN-03 sample default)`
              : ''}
          {integrations.model_host
            ? ` · ${integrations.model_host}${
                !identityProvisional && hostProvisional ? ' (OPEN-03 sample default)' : ''
              }`
            : identityProvisional
              ? ` · ${OPEN03_SAMPLE.host} (OPEN-03 sample default)`
              : ''}
          {identityProvisional
            ? ' · OPEN-03 sample default (not a live run)'
            : ''}
          {integrations.model_open_weight_confirmed ? ' · open-weight confirmed' : ' · open-weight not confirmed'}
          {integrations.model_key_configured ? ' · key present' : ' · key missing'}
          {integrations.model_caps_configured
            ? ` · caps ${integrations.model_max_input_chars || '?'} / ${integrations.model_max_output_tokens || '?'}${
                capsProvisional ? ' (OPEN-03 sample default)' : ''
              }`
            : ' · caps missing'}
          {integrations.typesafe_configured ? ' · Jev ready' : ' · Jev key missing'}
          {integrations.scraper_token_configured ? ' · scraper token set' : ' · scraper token missing'}
          {integrations.catalogue_auto_publish_new
            ? ' · new events auto-publish'
            : ' · new events await operator publish'}
          .
          {weightsHref ? (
            <>
              {' '}
              <a href={weightsHref} target="_blank" rel="noreferrer">
                Weights
                {weightsProvisional ? ' (OPEN-03 sample default)' : ''}
              </a>
            </>
          ) : null}
          {licenseHref ? (
            <>
              {' '}
              <a href={licenseHref} target="_blank" rel="noreferrer">
                Licence
                {licenseProvisional ? ' (OPEN-03 sample default)' : ''}
              </a>
            </>
          ) : null}{' '}
          Secrets stay on the server.
        </p>
      ) : null}
    </>
  );
}
