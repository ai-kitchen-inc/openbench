/** Shared Bahasa Indonesia UI strings. One-off strings live inline in their
 * components; only copy reused across files belongs here. */
export const APP_NAME = "SSS";
export const APP_TAGLINE = "Asisten Pengetahuan Cerdas";
export const FOOTER_ATTRIBUTION = `© ${new Date().getFullYear()} ${APP_NAME}`;

export const LOCAL_ROLE = {
  viewAsUser: "Lihat sebagai Pengguna",
  backToAdmin: "Kembali ke Admin",
} as const;

export const LIVE_DASHBOARD = {
  live: "Live",
  connecting: "Menghubungkan…",
  offline: "Koneksi terputus, mencoba lagi…",
  unavailable: "Dasbor tidak tersedia lagi",
  updated: "diperbarui",
  refresh: "Muat ulang data",
  loading: "Memuat dasbor…",
  notFound: "Dasbor tidak ditemukan.",
  loadFailed: "Dasbor tidak dapat dimuat.",
} as const;

export const COMMON = {
  signOut: "Keluar",
  close: "Tutup",
  cancel: "Batal",
  remove: "Hapus",
  refresh: "Segarkan",
  loading: "Memuat...",
  save: "Simpan",
  apply: "Terapkan",
  retry: "Coba Lagi",
} as const;
