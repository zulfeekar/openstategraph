import { useEffect, useState } from 'react';
import { KeyRound, RotateCcw, TriangleAlert } from 'lucide-react';
import {
  Badge,
  Button,
  Field,
  Icon,
  IconTile,
  TextInput,
} from '@design/primitives';
import { AbstractLLMProvider } from '@core/providers/ILLMProvider';
import { OllamaProvider } from '@core/providers/OllamaProvider';
import { useWorkbench } from '@app/WorkbenchContext';
import { Dialog } from './Dialog';
import './overlays.css';

/**
 * API keys and endpoints, one row per registered provider.
 *
 * Built from the provider registry, so a newly registered vendor appears here
 * with no changes — including its own credentials hint and model list.
 *
 * The storage warning is prominent on purpose. Keys entered here are held in
 * this browser, and a user handing over a production key deserves to know
 * that before they paste it, not in a changelog.
 */
export function CredentialsDialog({ onClose }: { onClose: () => void }) {
  const workbench = useWorkbench();
  const [, setVersion] = useState(0);
  const refresh = () => setVersion((value) => value + 1);

  useEffect(() => workbench.providers.onChange(refresh), [workbench]);

  return (
    <Dialog
      title="Models and credentials"
      subtitle="Dyflow runs offline against mock data by default. Add a key to use a real model."
      icon={KeyRound}
      onClose={onClose}
      footer={
        <>
          <Button
            icon={<Icon glyph={RotateCcw} size="sm" />}
            onClick={() => void workbench.providers.refreshModels()}
          >
            Refresh models
          </Button>
          <Button variant="primary" onClick={onClose}>
            Done
          </Button>
        </>
      }
    >
      <p className="dialog__warning">
        <Icon glyph={TriangleAlert} size="sm" />
        <span>
          Keys are stored in this browser&rsquo;s local storage and sent directly from this page to
          the provider. Use a scoped, revocable key — and prefer a server-side deployment for
          anything shared.
        </span>
      </p>

      {workbench.providers.list().map((provider) => {
        const configured = provider.isConfigured();
        const isOllama = provider instanceof OllamaProvider;

        return (
          <section key={provider.id} className="provider">
            <div className="provider__head">
              <IconTile glyph={KeyRound} size="sm" iconSize="xs" />
              <span className="provider__name">{provider.label}</span>
              <Badge tone={configured ? 'success' : 'neutral'}>
                {configured ? 'ready' : provider.requiresApiKey ? 'needs key' : 'check endpoint'}
              </Badge>
            </div>

            {provider.requiresApiKey ? (
              <Field label="API key" hint={provider.credentialsHint}>
                <TextInput
                  type="password"
                  mono
                  autoComplete="off"
                  placeholder="Paste key…"
                  value={workbench.providers.getApiKey(provider.id) ?? ''}
                  onChange={(event) => {
                    workbench.providers.setApiKey(provider.id, event.target.value || null);
                    refresh();
                  }}
                />
              </Field>
            ) : (
              <p className="provider__hint">
                {provider.credentialsHint ?? 'No credentials required.'}
              </p>
            )}

            {isOllama ? (
              <Field label="Endpoint">
                <TextInput
                  mono
                  placeholder="http://localhost:11434"
                  defaultValue=""
                  onChange={(event) =>
                    workbench.providers.setBaseUrl(provider.id, event.target.value || null)
                  }
                />
              </Field>
            ) : null}

            <span className="provider__models">
              {provider.models.length === 0
                ? 'No models available'
                : `${provider.models.length} model${provider.models.length === 1 ? '' : 's'}: ${provider.models
                    .slice(0, 4)
                    .map((model) => model.id)
                    .join(', ')}${provider.models.length > 4 ? '…' : ''}`}
            </span>
          </section>
        );
      })}

      <Button
        variant="danger"
        onClick={() => {
          for (const provider of workbench.providers.list()) {
            if (provider instanceof AbstractLLMProvider && provider.requiresApiKey) {
              workbench.providers.setApiKey(provider.id, null);
            }
          }
          refresh();
        }}
      >
        Forget all keys
      </Button>
    </Dialog>
  );
}
