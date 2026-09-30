import { useCallback, useEffect, useState } from "react";
import {
  getCapabilities,
  listGroups,
  putCapabilities,
  readErrorMessage,
  type CapabilitiesState,
  type CapabilityDefinition,
  type GroupItem,
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
  const [groups, setGroups] = useState<GroupItem[]>([]);
  const [isLoading, setIsLoading] = useState(true);
  const [loadError, setLoadError] = useState("");
  const [savingId, setSavingId] = useState<string | null>(null);

  const load = useCallback(async () => {
    setIsLoading(true);
    setLoadError("");
    try {
      const [capabilities, groupList] = await Promise.all([getCapabilities(), listGroups()]);
      setState(capabilities);
      setGroups(groupList);
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

  const handleGroupOverride = useCallback(
    async (groupId: string, definition: CapabilityDefinition, raw: string) => {
      setSavingId(`${groupId}.${definition.id}`);
      try {
        const value = raw === "inherit" ? null : raw === "on";
        const resolved = await putCapabilities({
          groups: { [groupId]: { [definition.id]: value } },
        });
        setState(resolved);
        showToast(`Pengecualian ${definition.label} untuk ${groupId} disimpan.`, "success");
      } catch (error) {
        showToast(
          `Gagal menyimpan pengecualian grup: ${readErrorMessage(error)}`,
          "error",
        );
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

      {groups.length > 0 && (
        <section className="panel-section" aria-label="Pengecualian per grup">
          <div className="panel-section__header">
            <div>
              <div className="panel-section__title">Pengecualian per Grup</div>
              <div className="panel-section__subtitle">
                Menimpa pengaturan peran user untuk anggota grup tertentu. "Ikut peran"
                menghapus pengecualian.
              </div>
            </div>
          </div>
          <div className="panel-section__body">
            {groups.map((group) => (
              <div className="cap-group" key={group.id}>
                <div className="cap-row">
                  <div className="cap-row__main">
                    <div className="cap-row__label">{group.name}</div>
                    <div className="cap-row__desc">{group.id}</div>
                  </div>
                </div>
                {routeDefinitions.map((definition) => {
                  const override = state.groups?.[group.id]?.[definition.id];
                  const current =
                    override === undefined ? "inherit" : override ? "on" : "off";
                  return (
                    <div className="cap-row settings-model-row" key={definition.id}>
                      <div className="cap-row__main">
                        <div className="cap-row__label">{definition.label}</div>
                      </div>
                      <select
                        className="settings-model-select"
                        aria-label={`${group.name}: ${definition.label}`}
                        value={current}
                        disabled={savingId !== null}
                        onChange={(event) =>
                          void handleGroupOverride(group.id, definition, event.target.value)
                        }
                      >
                        <option value="inherit">Ikut peran</option>
                        <option value="on">Aktif</option>
                        <option value="off">Nonaktif</option>
                      </select>
                    </div>
                  );
                })}
              </div>
            ))}
          </div>
        </section>
      )}
    </>
  );
}
