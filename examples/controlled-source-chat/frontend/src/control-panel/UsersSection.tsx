import { useCallback, useEffect, useState, type FormEvent } from "react";
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
      showToast(`Could not load users: ${readErrorMessage(error)}`, "error");
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
    <section className="panel-section" aria-label="User accounts">
      <div className="panel-section__header">
        <div>
          <div className="panel-section__title">
            <UsersIcon />
            Users
          </div>
          <div className="panel-section__subtitle">
            Accounts that can sign in. Admins manage sources and tools; guests only chat.
          </div>
        </div>
        <button
          type="button"
          className="panel-button"
          onClick={() => setAddOpen(!addOpen)}
          disabled={isMutating}
        >
          Add user
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
                showToast(`User added: ${username}`, "success");
              })
            }
          />
        )}

        {isLoading ? (
          <div className="sources-list__empty">Loading users...</div>
        ) : (
          <div className="sources-list">
            {users.map((user) => (
              <div key={user.username} className="source-row">
                <div
                  className={`source-row__badge${
                    user.role === "admin" ? " source-row__badge--filled" : ""
                  }`}
                >
                  {user.role}
                </div>
                <div className="source-row__main">
                  <div className="source-row__name">
                    {user.username}
                    {user.username === currentUsername ? " (you)" : ""}
                  </div>
                  {user.builtin && <div className="source-row__meta">Built-in account</div>}
                </div>
                {!user.builtin && user.username !== currentUsername && (
                  <button
                    type="button"
                    className="source-row__remove"
                    aria-label={`Remove ${user.username}`}
                    disabled={isMutating}
                    onClick={() => void runMutation(() => deleteUser(user.username))}
                  >
                    <svg
                      aria-hidden="true"
                      width="14"
                      height="14"
                      viewBox="0 0 24 24"
                      fill="none"
                      stroke="currentColor"
                      strokeWidth="2"
                      strokeLinecap="round"
                    >
                      <line x1="18" y1="6" x2="6" y2="18" />
                      <line x1="6" y1="6" x2="18" y2="18" />
                    </svg>
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
        placeholder="Username (lowercase letters, digits, . _ -)"
        value={username}
        onChange={(event) => setUsername(event.target.value)}
        autoComplete="off"
        required
      />
      <input
        type="password"
        placeholder="Password (at least 6 characters)"
        value={password}
        onChange={(event) => setPassword(event.target.value)}
        autoComplete="new-password"
        minLength={6}
        required
      />
      <select value={role} onChange={(event) => setRole(event.target.value as Role)}>
        <option value="guest">Guest — chat only</option>
        <option value="admin">Admin — full control panel</option>
      </select>
      <div className="sources-form__row">
        <button type="submit" className="panel-button panel-button--primary" disabled={disabled}>
          Add user
        </button>
      </div>
    </form>
  );
}

function UsersIcon() {
  return (
    <svg
      aria-hidden="true"
      width="16"
      height="16"
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth="1.5"
      strokeLinecap="round"
      strokeLinejoin="round"
    >
      <path d="M17 21v-2a4 4 0 0 0-4-4H5a4 4 0 0 0-4 4v2" />
      <circle cx="9" cy="7" r="4" />
      <path d="M23 21v-2a4 4 0 0 0-3-3.87" />
      <path d="M16 3.13a4 4 0 0 1 0 7.75" />
    </svg>
  );
}
