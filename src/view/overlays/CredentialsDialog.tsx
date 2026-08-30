import { useEffect, useState } from 'react';
import { KeyRound, RotateCcw, TriangleAlert } from 'lucide-react';
import { Badge, Button, Field, Icon, IconTile, TextInput } from '@design/primitives';
import { AbstractLLMProvider } from '@core/providers/ILLMProvider';
import { RuntimeClient, type ProviderStatus } from '@core/runtime/RuntimeClient';
import { serverReadiness } from '@core/providers/serverReadiness';
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

  // What the **server** holds, which is a different machine from this one and
  // was the whole defect: this dialog could only read the browser's store, so
  // it told a QA analyst the product runs "offline against mock data" on a
  // server with three working keys (ticket 04).
  const [onServer, setOnServer] = useState<readonly ProviderStatus[] | null>(null);
  // Which `.env` the server's own process read — or didn't — in its own
  // words (providers-and-credentials/13). `null` until it answers.
  const [serverEnvironment, setServerEnvironment] = useState<string | null>(null);
  // What a run through the default provider will do right now, in the
  // server's own words (providers-and-credentials/14). Replaces this
  // dialog's own former claim — "runs use mock data" — which stopped being
  // true when the Run button was rewired to a real backend run and stayed
  // wrong here for a session anyway.
  const [runReadiness, setRunReadiness] = useState<string | null>(null);
  useEffect(() => {
    let live = true;
    void new RuntimeClient().providers().then((result) => {
      if (!result.ok) return;
      // Published as well as held: this dialog was the only surface reading the
      // server, and the picker, the reasoning row and the onboarding hint went
      // on contradicting it from browser-local keys. Every answer this dialog
      // gets is now the answer they read (providers-and-credentials 06).
      serverReadiness.recordProviders(result.value.rows, result.value.runReadiness);
      if (live) {
        setOnServer(result.value.rows);
        setServerEnvironment(result.value.environment);
        setRunReadiness(result.value.runReadiness);
      }
    });
    return () => {
      live = false;
    };
  }, []);
  const serverStatus = (id: string) => onServer?.find((row) => row.name === id) ?? null;
  /** True once the server has answered and simply does not know this provider.
   *  Mock is the case: it is a browser-only preview provider, so "Server:
   *  asking…" would hang there forever waiting for a row that never comes. */
  const serverDoesNotKnow = (id: string) => onServer !== null && !serverStatus(id);

  /** What a real call last said about this provider, once one has been made. */
  const [verified, setVerified] = useState<Record<string, 'ok' | string>>({});
  const [verifying, setVerifying] = useState<string | null>(null);

  const badgeLabel = (id: string): string => {
    const outcome = verified[id];
    if (outcome === 'ok') return 'ready';
    if (outcome) return 'not valid';
    const status = serverStatus(id);
    if (status?.configured) return 'ready';
    if (workbench.providers.get(id)?.isConfigured()) return 'preview only';
    return 'needs key';
  };

  const badgeTone = (id: string): 'success' | 'danger' | 'neutral' => {
    const outcome = verified[id];
    if (outcome === 'ok') return 'success';
    if (outcome) return 'danger';
    return serverStatus(id)?.configured || workbench.providers.get(id)?.isConfigured()
      ? 'success'
      : 'neutral';
  };

  const verify = async (id: string) => {
    setVerifying(id);
    const result = await new RuntimeClient().verifyProvider(id);
    setVerifying(null);
    setVerified((current) => ({
      ...current,
      [id]: result.ok && result.value.ok ? 'ok' : result.ok ? result.value.detail : result.error,
    }));
  };
  const serverHasAny = (onServer ?? []).some((row) => row.configured);

  return (
    <Dialog
      title="Models and credentials"
      subtitle={
        // Said unconditionally, and so was false on any configured server.
        // Until the server answers, claim nothing rather than guess wrong.
        onServer === null
          ? 'Where each provider gets its key, on the server and in this browser.'
          : serverHasAny
            ? 'The server is configured and runs against real models. Keys here are for the canvas preview only.'
            : // providers-and-credentials/14: this used to say "runs use mock
              // data", which stopped being true once Run was rewired to a real
              // backend request — pressing it on an unconfigured server 500s
              // instead. `runReadiness` is the server's own sentence for why,
              // the same one `openstategraph providers` and `openstategraph
              // serve` print.
              (runReadiness ?? 'No provider is configured on the server.')
      }
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
          Keys belong in <code>.env</code> on the server, which is gitignored and never reaches this
          page; keys held in this browser exist only for the local canvas preview, and cannot be
          typed in here any more. Copy <code>.env.example</code> to <code>.env</code>, fill in the
          variable for your provider, and restart the backend.
        </span>
      </p>

      {/* Which environment the rows above describe — providers-and-credentials/13.
          `openstategraph providers` and this server can read two different
          `.env` files; this is that answer, in the server's own words, so a
          reader with keys in `.env` can tell whether the server they started
          actually has them. */}
      {serverEnvironment ? (
        <p className="provider__hint">Server environment: {serverEnvironment}</p>
      ) : null}

      {workbench.providers.list().map((provider) => {
        // The redacted form is all this component can ever obtain.
        const redacted = workbench.providers.describeApiKey(provider.id);

        return (
          <section key={provider.id} className="provider">
            <div className="provider__head">
              <IconTile glyph={KeyRound} size="sm" iconSize="xs" />
              <span className="provider__name">{provider.label}</span>
              {/* The badge answers "can a run use this?", so it reads the
                  **server** first: that is where real runs happen. It used to
                  read only the browser store, so a provider the server was
                  configured for showed "needs key" directly above a line
                  saying it was configured (ticket 04). */}
              {/* Three states, and the middle one is the point (ticket 04):
                  a key that is *set* is not a key that *works*. `not valid` is
                  only ever shown after a real call came back rejected — it is
                  never guessed from the value's shape, because a well-formed
                  key with no credit looks exactly like a working one. */}
              <Badge tone={badgeTone(provider.id)}>{badgeLabel(provider.id)}</Badge>
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
                  // The server's hint first: that is the key a *run* uses.
                  // A browser-held key is a preview-only thing and says so in
                  // the field's own hint below.
                  value={serverStatus(provider.id)?.keyHint ?? redacted ?? ''}
                  placeholder={`Add ${provider.label} key in .env`}
                />
              </Field>
            ) : (
              <p className="provider__hint">
                {provider.credentialsHint ?? 'No credentials required.'}
              </p>
            )}

            {/* The server's answer, per provider. Never a key, not even
                masked: naming the *variable* is what a person can act on, and
                a mask would contradict the 401 handler that deliberately drops
                OpenAI's own masked fragment. */}
            {serverDoesNotKnow(provider.id) ? null : (
              <p className="provider__hint">
                {(() => {
                  const status = serverStatus(provider.id);
                  if (!status) return 'Server: asking…';
                  if (status.configured) {
                    return `Server: configured via ${status.configuredBy ?? 'its environment'} ✓`;
                  }
                  return `Server: not configured — set ${status.envVars.join(' or ') || 'its variable'} in .env`;
                })()}
              </p>
            )}

            {/* Which model a run gets when the field is left empty
                (`the-cost-of-one-more/14`). The line above it says whether
                this server can reach the provider at all; this one says what
                it reaches for, which is the fact the picker could not state —
                every model in the list beside it is one somebody chose, and
                the default is the one nobody does.

                A **server** answer, so it renders only where the server's
                other answers do, and only when one arrived: `defaultModel` is
                `''` when the row did not carry it, and an empty default is
                silence rather than a sentence about nothing. */}
            {serverStatus(provider.id)?.defaultModel ? (
              <p className="provider__hint">
                {`Server default: ${serverStatus(provider.id)?.defaultModel} — used when a run names no model`}
              </p>
            ) : null}

            {serverStatus(provider.id)?.configured ? (
              <Button onClick={() => void verify(provider.id)} disabled={verifying === provider.id}>
                {verifying === provider.id ? 'Checking…' : 'Verify key'}
              </Button>
            ) : null}
            {verified[provider.id] && verified[provider.id] !== 'ok' ? (
              <p className="provider__hint">{verified[provider.id]}</p>
            ) : null}

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
              // The placeholder is the *effect of leaving it blank*, not an
              // example to copy. It read `http://localhost:11434` while the
              // default was localhost; now that the default is the cloud, the
              // old placeholder would have described the opposite of what an
              // empty field does.
              <Field
                label="Endpoint"
                hint="Leave blank for the cloud. Set it to reach a daemon you run."
              >
                <TextInput
                  mono
                  placeholder="https://ollama.com"
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
