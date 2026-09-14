import { useCallback, useEffect, useState, type FormEvent } from "react";
import { UsersIcon, XIcon } from "../brand/icons";
import { useToast } from "../Toast";
import { readErrorMessage } from "./sourcesApi";
import { addUser, deleteUser, listUsers, updateUser, type Role, type UserItem } from "./usersApi";

const EMAIL_PATTERN = /^[^\s@]+@[^\s@]+\.[^\s@]+$/;

export function UsersSection({ currentEmail }: { currentEmail: string }) {
  // Only the stable show() callback — depending on the whole context object
  // (which changes with every toast) would re-create refresh and retrigger
  // the load effect in a feedback loop.
  const { show: showToast } = useToast();
  const [users, setUsers] = useState<UserItem[]>([]);
  const [isLoading, setIsLoading] = useState(true);
  const [isMutating, setIsMutating] = useState(false);
  const [addOpen, setAddOpen] = useState(false);

  const refresh = useCallback(async () => {
    try {
      setUsers(await listUsers());
    } catch (error) {
      showToast(`Gagal memuat pengguna: ${readErrorMessage(error)}`, "error");
    } finally {
      setIsLoading(false);
    }
  }, [showToast]);

  useEffect(() => {
    void refresh();
  }, [refresh]);

  const runMutation = useCallback(
    async (mutation: () => Promise<void>) => {
      setIsMutating(true);
      try {
        await mutation();
        await refresh();
      } catch (error) {
        showToast(readErrorMessage(error), "error");
      } finally {
        setIsMutating(false);
      }
    },
    [refresh, showToast],
  );

  return (
    <section className="panel-section" aria-label="Akun pengguna">
      <div className="panel-section__header">
        <div>
          <div className="panel-section__title">
            <UsersIcon />
            Daftar Pengguna
          </div>
          <div className="panel-section__subtitle">
            Kelola akun Google yang dapat masuk beserta perannya.
          </div>
        </div>
        <button
          type="button"
          className="panel-button"
          onClick={() => setAddOpen(!addOpen)}
          disabled={isMutating}
        >
          Tambah Pengguna
        </button>
      </div>
      <div className="panel-section__body">
        {addOpen && (
          <AddUserForm
            disabled={isMutating}
            onSubmit={(email, role, displayName) =>
              void runMutation(async () => {
                await addUser(email, role, displayName);
                setAddOpen(false);
                showToast(`Pengguna ditambahkan: ${email}`, "success");
              })
            }
          />
        )}

        {isLoading ? (
          <div className="sources-list__empty">Memuat pengguna...</div>
        ) : (
          <div className="sources-list">
            {users.map((user) => (
              <div key={user.email} className="source-row">
                <div
                  className={`source-row__badge${
                    user.role === "admin" ? " source-row__badge--filled" : ""
                  }`}
                >
                  {user.role === "admin" ? "Admin" : "Pengguna"}
                </div>
                <div className="source-row__main">
                  <div className="source-row__name">
                    {user.email}
                    {user.email === currentEmail ? " (Anda)" : ""}
                  </div>
                  {user.displayName && (
                    <div className="source-row__meta">{user.displayName}</div>
                  )}
                </div>
                <select
                  aria-label={`Peran ${user.email}`}
                  value={user.role}
                  disabled={isMutating || user.email === currentEmail}
                  onChange={(event) =>
                    void runMutation(async () => {
                      await updateUser(user.email, { role: event.target.value as Role });
                      showToast(`Peran ${user.email} diperbarui`, "success");
                    })
                  }
                >
                  <option value="user">user</option>
                  <option value="admin">admin</option>
                </select>
                {user.email !== currentEmail && (
                  <button
                    type="button"
                    className="source-row__remove"
                    aria-label={`Hapus ${user.email}`}
                    disabled={isMutating}
                    onClick={() => void runMutation(() => deleteUser(user.email))}
                  >
                    <XIcon size={14} />
                  </button>
                )}
              </div>
            ))}
          </div>
        )}
      </div>
    </section>
  );
}

function AddUserForm({
  disabled,
  onSubmit,
}: {
  disabled: boolean;
  onSubmit: (email: string, role: Role, displayName?: string) => void;
}) {
  const [email, setEmail] = useState("");
  const [displayName, setDisplayName] = useState("");
  const [role, setRole] = useState<Role>("user");
  const [error, setError] = useState("");

  const handleSubmit = (event: FormEvent) => {
    event.preventDefault();
    const normalized = email.trim().toLowerCase();
    if (!EMAIL_PATTERN.test(normalized)) {
      setError("Alamat email tidak valid.");
      return;
    }
    setError("");
    onSubmit(normalized, role, displayName.trim() || undefined);
  };

  return (
    <form className="sources-form" onSubmit={handleSubmit}>
      <input
        type="email"
        placeholder="Email akun Google (mis. nama@instansi.go.id)"
        value={email}
        onChange={(event) => setEmail(event.target.value)}
        autoComplete="off"
        required
      />
      <input
        type="text"
        placeholder="Nama tampilan (opsional)"
        value={displayName}
        onChange={(event) => setDisplayName(event.target.value)}
        autoComplete="off"
      />
      <select value={role} onChange={(event) => setRole(event.target.value as Role)} aria-label="Peran">
        <option value="user">user — hanya chat</option>
        <option value="admin">admin — panel kendali penuh</option>
      </select>
      {error && <div className="source-row__error">{error}</div>}
      <div className="sources-form__row">
        <button type="submit" className="panel-button panel-button--primary" disabled={disabled}>
          Tambah Pengguna
        </button>
      </div>
    </form>
  );
}
