import { UsersSection } from "../UsersSection";

export function UsersPage({ currentUsername }: { currentUsername: string }) {
  return (
    <>
      <div className="admin-page__header">
        <div className="admin-page__desc">
          Akun yang dapat masuk ke layanan. Admin mengelola sumber dan perangkat; tamu hanya dapat
          menggunakan chat.
        </div>
      </div>
      <UsersSection currentUsername={currentUsername} />
    </>
  );
}
