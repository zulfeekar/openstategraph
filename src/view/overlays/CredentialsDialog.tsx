import { useEffect, useState } from 'react';
import { KeyRound, RotateCcw, TriangleAlert } from 'lucide-react';
import { Badge, Button, Field, Icon, IconTile, TextInput } from '@design/primitives';
import { AbstractLLMProvider } from '@core/providers/ILLMProvider';
import { useWorkbench } from '@app/WorkbenchContext';
import { Dialog } from './Dialog';
import './overlays.css';

/**
 * Models and credentials — one row per registered provider.
 *
 * Built entirely from the provider registry, so a newly registered vendor
 * appears here with no change to this file: its own hint, its own model list,
 * and its own endpoint field if it declares `configurableEndpoint`. There is
 * no vendor literal left in this component.
 *
 * **Two states, and neither of them shows a key** (ticket 04):
 *
 * | Key | What the row shows |
 * | --- | --- |
 * | stored in this browser | `sk-…9WxZ`, read-only, with **Forget** |
 * | absent | a **disabled** input, `Add {provider} key in .env` |
 *
 * The input is disabled rather than merely discouraged because this dialog
 * used to render the raw key into `<TextInput value={…}>` — the secret sat in
 * the DOM and in React state, and it was re-fillable, so a mistyped paste
 * silently replaced a working key. The component can no longer obtain the raw
 * value at all: `ProviderRegistry.describeApiKey` is the only accessor it has,
 * and it returns the redacted form.
 *
 * **Which keys live where** is the reconciliation this ticket asked for, and
 * the dialog states it in one sentence rather than leaving it to a changelog:
 * browser-held keys exist *only* for the local canvas preview, which calls the
 * vendor directly from this page; every server-side and shared key belongs in
 * `.env`, which is gitignored and never reaches the browser. Existing stored
 * keys keep working and keep being forwarded to backend runs — they can be
 * read out and forgotten, just not typed in.
 */
export function CredentialsDialog({ onClose }: { onClose: () => void }) {
  const workbench = useWorkbench();
  const [, setVersion] = useState(0);
  const refresh = () => setVersion((value) => value + 1);

  useEffect(() => workbench.providers.onChange(refresh), [workbench]);

  return (
    <Dialog
      title="Models and credentials"
      subtitle="OpenStateGraph runs offline against mock data by default. Add a key to use a real model."
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
          Keys belong in <code>.env</code> on the server, which is gitignored and never reaches
          this page; keys held in this browser exist only for the local canvas preview, and cannot
          be typed in here any more. Copy <code>.env.example</code> to <code>.env</code>, fill in
          the variable for your provider, and restart the backend.
        </span>
      </p>

      {workbench.providers.list().map((provider) => {
        const configured = provider.isConfigured();
        // The redacted form is all this component can ever obtain.
        const redacted = workbench.providers.describeApiKey(provider.id);

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
              <Field
                label="API key"
                hint={
                  redacted
                    ? `Held in this browser for the canvas preview only. ${provider.credentialsHint ?? ''}`.trim()
                    : `Set ${provider.runtimeCredentialKey ?? 'the provider key'} in .env — see .env.example.`
                }
              >
                <TextInput
                  mono
                  disabled
                  readOnly
                  autoComplete="off"
                  // Never the value: `describeApiKey` is the only accessor
                  // this component has, and it cannot return one.
                  value={redacted ?? ''}
                  placeholder={`Add ${provider.label} key in .env`}
                />
              </Field>
            ) : (
              <p className="provider__hint">
                {provider.credentialsHint ?? 'No credentials required.'}
              </p>
            )}

            {redacted ? (
              <Button
                onClick={() => {
                  workbench.providers.setApiKey(provider.id, null);
                  refresh();
                }}
              >
                Forget this key
              </Button>
            ) : null}

            {provider.configurableEndpoint ? (
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
