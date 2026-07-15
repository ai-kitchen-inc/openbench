import { useCallback, useEffect, useState, type FormEvent } from "react";
import { UsersIcon, XIcon } from "../brand/icons";
import { useToast } from "../Toast";
import type { Role } from "../api";
import { readErrorMessage } from "./sourcesApi";
import { addUser, deleteUser, listUsers, type UserItem } from "./usersApi";

export function UsersSection({ currentUsername }: { currentUsername: string }) {
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
            Kelola akun yang dapat masuk beserta perannya.
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
            onSubmit={(username, password, role) =>
              void runMutation(async () => {
                await addUser(username, password, role);
                setAddOpen(false);
                showToast(`Pengguna ditambahkan: ${username}`, "success");
              })
            }
          />
        )}

        {isLoading ? (
          <div className="sources-list__empty">Memuat pengguna...</div>
        ) : (
          <div className="sources-list">
            {users.map((user) => (
              <div key={user.username} className="source-row">
                <div
                  className={`source-row__badge${
                    user.role === "admin" ? " source-row__badge--filled" : ""
                  }`}
                >
                  {user.role === "admin" ? "Admin" : "Tamu"}
                </div>
                <div className="source-row__main">
                  <div className="source-row__name">
                    {user.username}
                    {user.username === currentUsername ? " (Anda)" : ""}
                  </div>
                  {user.builtin && <div className="source-row__meta">Akun bawaan</div>}
                </div>
                {!user.builtin && user.username !== currentUsername && (
                  <button
                    type="button"
                    className="source-row__remove"
                    aria-label={`Hapus ${user.username}`}
                    disabled={isMutating}
                    onClick={() => void runMutation(() => deleteUser(user.username))}
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
  onSubmit: (username: string, password: string, role: Role) => void;
}) {
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [role, setRole] = useState<Role>("guest");

  const handleSubmit = (event: FormEvent) => {
    event.preventDefault();
    if (!username.trim() || !password) return;
    onSubmit(username.trim().toLowerCase(), password, role);
  };

  return (
    <form className="sources-form" onSubmit={handleSubmit}>
      <input
        type="text"
        placeholder="Nama pengguna (huruf kecil, angka, . _ -)"
        value={username}
        onChange={(event) => setUsername(event.target.value)}
        autoComplete="off"
        required
      />
      <input
        type="password"
        placeholder="Kata sandi (minimal 6 karakter)"
        value={password}
        onChange={(event) => setPassword(event.target.value)}
        autoComplete="new-password"
        minLength={6}
        required
      />
      <select value={role} onChange={(event) => setRole(event.target.value as Role)}>
        <option value="guest">Tamu — hanya chat</option>
        <option value="admin">Admin — panel kendali penuh</option>
      </select>
      <div className="sources-form__row">
        <button type="submit" className="panel-button panel-button--primary" disabled={disabled}>
          Tambah Pengguna
        </button>
      </div>
    </form>
  );
}
