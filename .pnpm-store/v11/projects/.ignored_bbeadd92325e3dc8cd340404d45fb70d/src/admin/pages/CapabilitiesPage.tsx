import { useCallback, useEffect, useState } from "react";
import {
  getCapabilities,
  putCapabilities,
  readErrorMessage,
  type CapabilitiesState,
  type CapabilityDefinition,
} from "../../account/api";
import { useToast } from "../../Toast";
import { COMMON } from "../../i18n/id";

function CapabilityRow({
  definition,
  checked,
  disabled,
  onToggle,
}: {
  definition: CapabilityDefinition;
  checked: boolean;
  disabled: boolean;
  onToggle: (next: boolean) => void;
}) {
  return (
    <div className="cap-row">
      <div className="cap-row__main">
        <div className="cap-row__label">{definition.label}</div>
        <div className="cap-row__desc">{definition.description}</div>
      </div>
      <button
        type="button"
        role="switch"
        className="switch"
        aria-checked={checked}
        aria-label={definition.label}
        disabled={disabled}
        onClick={() => onToggle(!checked)}
      />
    </div>
  );
}

export function CapabilitiesPage() {
  const { show: showToast } = useToast();
  const [state, setState] = useState<CapabilitiesState | null>(null);
  const [isLoading, setIsLoading] = useState(true);
  const [loadError, setLoadError] = useState("");
  const [savingId, setSavingId] = useState<string | null>(null);

  const load = useCallback(async () => {
    setIsLoading(true);
    setLoadError("");
    try {
      setState(await getCapabilities());
    } catch (error) {
      setLoadError(readErrorMessage(error));
    } finally {
      setIsLoading(false);
    }
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  const handleToggle = useCallback(
    async (definition: CapabilityDefinition, next: boolean) => {
      setSavingId(definition.id);
      try {
        const patch =
          definition.kind === "global"
            ? { global: { [definition.id]: next } }
            : { roles: { user: { [definition.id]: next } } };
        const resolved = await putCapabilities(patch);
        setState(resolved);
        showToast(
          `${definition.label} ${next ? "diaktifkan" : "dinonaktifkan"}.`,
          "success",
        );
      } catch (error) {
        // A 500 on a global flip means the setting was saved but the agent
        // reload failed (the old agent keeps serving) — surface the detail.
        showToast(`Gagal memperbarui ${definition.label}: ${readErrorMessage(error)}`, "error");
      } finally {
        setSavingId(null);
      }
    },
    [showToast],
  );

  if (isLoading) {
    return <div className="sources-list__empty">{COMMON.loading}</div>;
  }

  if (loadError || !state) {
    return (
      <div className="sources-list__empty">
        Gagal memuat kemampuan: {loadError}{" "}
        <button type="button" className="panel-button" onClick={() => void load()}>
          {COMMON.retry}
        </button>
      </div>
    );
  }

  const routeDefinitions = state.definitions.filter((item) => item.kind === "route");
  const globalDefinitions = state.definitions.filter((item) => item.kind === "global");

  return (
    <>
      <div className="admin-page__header">
        <div className="admin-page__desc">
          Atur fitur yang tersedia bagi pengguna berperan <strong>user</strong> serta sakelar
          global. Admin selalu memiliki semua kemampuan.
        </div>
      </div>

      <section className="panel-section" aria-label="Fitur pengguna">
        <div className="panel-section__header">
          <div>
            <div className="panel-section__title">Fitur Pengguna</div>
            <div className="panel-section__subtitle">
              Berlaku untuk semua akun berperan user. Perubahan tersimpan otomatis.
            </div>
          </div>
        </div>
        <div className="panel-section__body">
          <div className="cap-group">
            {routeDefinitions.map((definition) => (
              <CapabilityRow
                key={definition.id}
                definition={definition}
                checked={Boolean(state.roles.user[definition.id])}
                disabled={savingId !== null}
                onToggle={(next) => void handleToggle(definition, next)}
              />
            ))}
            {routeDefinitions.length === 0 && (
              <div className="sources-list__empty">Tidak ada fitur pengguna.</div>
            )}
          </div>
        </div>
      </section>

      <section className="panel-section" aria-label="Sakelar global">
        <div className="panel-section__header">
          <div>
            <div className="panel-section__title">Global</div>
            <div className="panel-section__subtitle">
              Berlaku untuk seluruh deployment (termasuk admin).
            </div>
          </div>
        </div>
        <div className="panel-section__body">
          <div className="cap-group">
            {globalDefinitions.map((definition) => (
              <CapabilityRow
                key={definition.id}
                definition={definition}
                checked={Boolean(state.global[definition.id])}
                disabled={savingId !== null}
                onToggle={(next) => void handleToggle(definition, next)}
              />
            ))}
            {globalDefinitions.length === 0 && (
              <div className="sources-list__empty">Tidak ada sakelar global.</div>
            )}
          </div>
        </div>
      </section>
    </>
  );
}
