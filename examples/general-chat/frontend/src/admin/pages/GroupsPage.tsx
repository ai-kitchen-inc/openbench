import { useCallback, useEffect, useState } from "react";
import {
  addGroup,
  addGroupTextSource,
  addGroupUrlSource,
  deleteGroup,
  deleteGroupSource,
  listGroups,
  listGroupSources,
  listUsers,
  readErrorMessage,
  updateUser,
  type GroupItem,
  type GroupSourceItem,
  type UserItem,
} from "../../account/api";
import { XIcon } from "../../brand/icons";
import { useToast } from "../../Toast";
import { COMMON } from "../../i18n/id";

function GroupDetail({
  group,
  users,
  onMembershipChange,
}: {
  group: GroupItem;
  users: UserItem[];
  onMembershipChange: () => void;
}) {
  const { show: showToast } = useToast();
  const [sources, setSources] = useState<GroupSourceItem[] | null>(null);
  const [sourceName, setSourceName] = useState("");
  const [sourceText, setSourceText] = useState("");
  const [sourceUrl, setSourceUrl] = useState("");
  const [memberEmail, setMemberEmail] = useState("");
  const [isBusy, setIsBusy] = useState(false);

  const members = users.filter((user) => user.group === group.id);
  const candidates = users.filter((user) => user.group !== group.id);

  const loadSources = useCallback(async () => {
    try {
      setSources(await listGroupSources(group.id));
    } catch (error) {
      showToast(`Gagal memuat sumber grup: ${readErrorMessage(error)}`, "error");
    }
  }, [group.id, showToast]);

  useEffect(() => {
    void loadSources();
  }, [loadSources]);

  const run = useCallback(
    async (action: () => Promise<void>, successMessage: string) => {
      setIsBusy(true);
      try {
        await action();
        showToast(successMessage, "success");
      } catch (error) {
        showToast(readErrorMessage(error), "error");
      } finally {
        setIsBusy(false);
      }
    },
    [showToast],
  );

  return (
    <div className="panel-section__body">
      <div className="cap-group">
        <div className="cap-row">
          <div className="cap-row__main">
            <div className="cap-row__label">Anggota ({members.length})</div>
            <div className="cap-row__desc">
              {members.length
                ? members.map((member) => member.email).join(", ")
                : "Belum ada anggota."}
            </div>
          </div>
        </div>
      </div>
      <form
        className="sources-form"
        onSubmit={(event) => {
          event.preventDefault();
          if (!memberEmail) return;
          void run(async () => {
            await updateUser(memberEmail, { group: group.id });
            setMemberEmail("");
            onMembershipChange();
          }, `Anggota ditambahkan ke ${group.name}.`);
        }}
      >
        <div className="sources-form__row">
          <select
            aria-label="Tambah anggota"
            value={memberEmail}
            onChange={(event) => setMemberEmail(event.target.value)}
          >
            <option value="">Pilih pengguna...</option>
            {candidates.map((user) => (
              <option key={user.email} value={user.email}>
                {user.email}
              </option>
            ))}
          </select>
          <button
            type="submit"
            className="panel-button panel-button--primary"
            disabled={isBusy || !memberEmail}
          >
            Tambah anggota
          </button>
        </div>
      </form>

      <div className="cap-group">
        <div className="cap-row">
          <div className="cap-row__main">
            <div className="cap-row__label">Sumber grup</div>
            <div className="cap-row__desc">
              Dokumen yang melandasi jawaban asisten khusus untuk anggota grup ini.
            </div>
          </div>
        </div>
      </div>
      {sources === null ? (
        <div className="sources-list__empty">{COMMON.loading}</div>
      ) : sources.length === 0 ? (
        <div className="sources-list__empty">Belum ada sumber grup.</div>
      ) : (
        <div className="sources-list">
          {sources.map((source) => (
            <div className="source-row" key={source.id}>
              <span className="source-row__badge source-row__badge--filled">
                {source.kind ?? "teks"}
              </span>
              <div className="source-row__main">
                <div className="source-row__name">{source.name}</div>
              </div>
              <button
                type="button"
                className="source-row__remove"
                aria-label={`Hapus ${source.name}`}
                disabled={isBusy}
                onClick={() =>
                  void run(async () => {
                    await deleteGroupSource(group.id, source.id);
                    await loadSources();
                  }, "Sumber grup dihapus.")
                }
              >
                <XIcon />
              </button>
            </div>
          ))}
        </div>
      )}
      <form
        className="sources-form"
        onSubmit={(event) => {
          event.preventDefault();
          if (!sourceText.trim()) return;
          void run(async () => {
            await addGroupTextSource(group.id, sourceName.trim() || "Teks", sourceText);
            setSourceName("");
            setSourceText("");
            await loadSources();
          }, "Sumber teks ditambahkan.");
        }}
      >
        <div className="sources-form__row">
          <input
            type="text"
            placeholder="Nama sumber"
            aria-label="Nama sumber"
            value={sourceName}
            onChange={(event) => setSourceName(event.target.value)}
          />
          <input
            type="text"
            placeholder="Tempel teks kebijakan/dokumen"
            aria-label="Teks sumber"
            value={sourceText}
            onChange={(event) => setSourceText(event.target.value)}
          />
          <button type="submit" className="panel-button" disabled={isBusy}>
            Tambah teks
          </button>
        </div>
        <div className="sources-form__row">
          <input
            type="url"
            placeholder="https://..."
            aria-label="URL sumber"
            value={sourceUrl}
            onChange={(event) => setSourceUrl(event.target.value)}
          />
          <button
            type="button"
            className="panel-button"
            disabled={isBusy || !sourceUrl.trim()}
            onClick={() =>
              void run(async () => {
                await addGroupUrlSource(group.id, sourceUrl.trim());
                setSourceUrl("");
                await loadSources();
              }, "Sumber URL ditambahkan.")
            }
          >
            Tambah URL
          </button>
        </div>
      </form>
    </div>
  );
}

export function GroupsPage() {
  const { show: showToast } = useToast();
  const [groups, setGroups] = useState<GroupItem[] | null>(null);
  const [users, setUsers] = useState<UserItem[]>([]);
  const [loadError, setLoadError] = useState("");
  const [newName, setNewName] = useState("");
  const [newDescription, setNewDescription] = useState("");
  const [expanded, setExpanded] = useState<string | null>(null);
  const [isBusy, setIsBusy] = useState(false);

  const load = useCallback(async () => {
    setLoadError("");
    try {
      const [groupList, userList] = await Promise.all([listGroups(), listUsers()]);
      setGroups(groupList);
      setUsers(userList);
    } catch (error) {
      setLoadError(readErrorMessage(error));
    }
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  const createGroup = useCallback(async () => {
    if (!newName.trim()) return;
    setIsBusy(true);
    try {
      await addGroup(newName.trim(), newDescription.trim() || undefined);
      setNewName("");
      setNewDescription("");
      await load();
      showToast("Grup dibuat.", "success");
    } catch (error) {
      showToast(`Gagal membuat grup: ${readErrorMessage(error)}`, "error");
    } finally {
      setIsBusy(false);
    }
  }, [load, newDescription, newName, showToast]);

  const removeGroup = useCallback(
    async (group: GroupItem) => {
      if (
        !window.confirm(
          `Hapus grup "${group.name}"? Anggota dilepas dan sumber grup ikut terhapus.`,
        )
      ) {
        return;
      }
      setIsBusy(true);
      try {
        await deleteGroup(group.id);
        await load();
        showToast("Grup dihapus.", "success");
      } catch (error) {
        showToast(`Gagal menghapus grup: ${readErrorMessage(error)}`, "error");
      } finally {
        setIsBusy(false);
      }
    },
    [load, showToast],
  );

  if (groups === null && !loadError) {
    return <div className="sources-list__empty">{COMMON.loading}</div>;
  }

  if (loadError) {
    return (
      <div className="sources-list__empty">
        Gagal memuat grup: {loadError}{" "}
        <button type="button" className="panel-button" onClick={() => void load()}>
          {COMMON.retry}
        </button>
      </div>
    );
  }

  return (
    <>
      <div className="admin-page__header">
        <div className="admin-page__desc">
          Grup membagi pengguna ke ruang kerja tim: sumber pengetahuan per grup dan
          pengecualian kemampuan per grup.
        </div>
      </div>

      <section className="panel-section" aria-label="Grup">
        <div className="panel-section__header">
          <div>
            <div className="panel-section__title">Grup</div>
            <div className="panel-section__subtitle">
              {groups?.length ?? 0} grup terdaftar.
            </div>
          </div>
        </div>
        <div className="panel-section__body">
          <form
            className="sources-form"
            onSubmit={(event) => {
              event.preventDefault();
              void createGroup();
            }}
          >
            <div className="sources-form__row">
              <input
                type="text"
                placeholder="Nama grup (mis. Tim Keuangan)"
                aria-label="Nama grup"
                value={newName}
                onChange={(event) => setNewName(event.target.value)}
              />
              <input
                type="text"
                placeholder="Deskripsi (opsional)"
                aria-label="Deskripsi grup"
                value={newDescription}
                onChange={(event) => setNewDescription(event.target.value)}
              />
              <button
                type="submit"
                className="panel-button panel-button--primary"
                disabled={isBusy || !newName.trim()}
              >
                Buat grup
              </button>
            </div>
          </form>

          {groups && groups.length === 0 ? (
            <div className="sources-list__empty">Belum ada grup.</div>
          ) : (
            <div className="sources-list">
              {(groups ?? []).map((group) => (
                <div key={group.id}>
                  <div className="source-row">
                    <span className="source-row__badge source-row__badge--filled">
                      {group.memberCount}
                    </span>
                    <div className="source-row__main">
                      <div className="source-row__name">{group.name}</div>
                      <div className="source-row__meta">
                        {group.id}
                        {group.description ? ` · ${group.description}` : ""}
                      </div>
                    </div>
                    <button
                      type="button"
                      className="panel-button"
                      onClick={() =>
                        setExpanded(expanded === group.id ? null : group.id)
                      }
                    >
                      {expanded === group.id ? "Tutup" : "Kelola"}
                    </button>
                    <button
                      type="button"
                      className="source-row__remove"
                      aria-label={`Hapus ${group.name}`}
                      disabled={isBusy}
                      onClick={() => void removeGroup(group)}
                    >
                      <XIcon />
                    </button>
                  </div>
                  {expanded === group.id && (
                    <GroupDetail
                      group={group}
                      users={users}
                      onMembershipChange={() => void load()}
                    />
                  )}
                </div>
              ))}
            </div>
          )}
        </div>
      </section>
    </>
  );
}
