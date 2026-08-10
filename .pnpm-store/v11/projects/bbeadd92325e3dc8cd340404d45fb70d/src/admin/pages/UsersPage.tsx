import { UsersSection } from "../UsersSection";

export function UsersPage({ currentEmail }: { currentEmail: string }) {
  return (
    <>
      <div className="admin-page__header">
        <div className="admin-page__desc">
          Akun Google yang dapat masuk ke layanan. Admin mengelola sumber, persona, dan
          kemampuan; pengguna memakai chat sesuai kemampuan yang diaktifkan.
        </div>
      </div>
      <UsersSection currentEmail={currentEmail} />
    </>
  );
}
