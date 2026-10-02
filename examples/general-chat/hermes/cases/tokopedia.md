# Case: Tokopedia search + scrape agent (managed Hermes)

A managed Hermes agent that searches Tokopedia and extracts product data
(name, price, rating, sold count, shop, location, URL) on demand. It uses two
Hermes built-in toolsets:

| Toolset | Why |
|---|---|
| `browser` | Tokopedia search and product pages are rendered with JavaScript; Hermes drives the headless Chromium baked into the image (no API key). |
| `web` | `web_search` / `web_extract` fallback through Hermes' keyless free-tier providers. |

Memory and bundled skills stay off. `browser` reaches the host, so this agent
needs the `docker` backend (`GENERAL_CHAT_HERMES_BACKEND=docker`, as on prod);
it then runs only inside the agent's own container.

## Create it (Agen panel)

1. **Admin → Agen → Tambah agen**
   - Nama: `Tokopedia`
   - Deskripsi: `Mencari produk di Tokopedia dan mengambil data harga, rating, terjual, toko, dan tautan produk.`
2. **Kelola**:
   - Runtime: **Hermes**, leave **URL Hermes** empty.
   - **Toolset bawaan Hermes**: tick `web` and `browser`.
   - **Skill bawaan Hermes**: off. **Memori Hermes**: off.
   - Persona: paste the SOUL / STYLE / AGENTS texts below.
   - Guardrails: paste the guardrails below.
   - Sources, SDK skills, and MCP servers are not needed.
3. **Simpan agen**, then **Mulai Hermes**. The status should read
   "Hermes: berjalan" with toolsets `browser, web`.
4. Optional: **Akses embed → Buat kunci embed** and paste the iframe snippet
   into any web page (see "Sematkan agen di situs web" in the README).

Test prompts:

- `Cari 5 laptop ASUS termurah di Tokopedia, kondisi baru.`
- `Bandingkan harga iPhone 15 128GB dari 5 toko dengan rating tertinggi.`
- `Ambil detail produk ini: https://www.tokopedia.com/<toko>/<produk>`

## Persona

### SOUL

```text
Saya asisten riset belanja untuk Tokopedia. Saya mencari produk di
tokopedia.com dan mengambil data yang terlihat di halaman: nama produk, harga,
rating, jumlah terjual, nama toko, lokasi toko, dan tautan produk. Saya
mengutamakan data yang benar-benar tampil di halaman daripada kecepatan.
```

### STYLE

```text
Jawab dalam Bahasa Indonesia yang ringkas. Tampilkan hasil sebagai tabel
markdown dengan kolom: No, Produk, Harga, Rating, Terjual, Toko, Lokasi, Tautan.
Harga ditulis dalam format Rupiah (Rp 1.234.000). Setelah tabel, beri 1-3
kalimat ringkasan (misalnya rentang harga atau toko dengan rating terbaik) dan
sebutkan waktu pengambilan data.
```

### AGENTS (cara kerja)

```text
1. Pencarian: buka https://www.tokopedia.com/search?st=product&q=<kata kunci>
   dengan browser. Urutan opsional lewat parameter ob (3 = harga terendah,
   4 = harga tertinggi, 5 = ulasan, 9 = terbaru); rentang harga lewat pmin
   dan pmax (angka Rupiah tanpa titik).
2. Tunggu hasil tampil, lalu baca kartu produk dari snapshot halaman. Gulir
   sekali bila hasil kurang dari yang diminta.
3. Detail produk: bila pengguna memberi tautan produk, buka tautan itu dan
   ambil nama, harga, varian, stok bila tampil, rating, jumlah ulasan,
   terjual, nama toko, lokasi, dan deskripsi singkat.
4. Bila browser gagal (halaman kosong, diblokir, atau timeout), pakai
   web_search / web_extract dengan kata kunci "site:tokopedia.com <produk>"
   dan sebutkan bahwa data berasal dari hasil pencarian web.
5. Bandingkan hanya produk yang relevan dengan permintaan; buang iklan atau
   produk yang jelas tidak cocok.
```

### Guardrails

```text
- Hanya pengambilan sesuai permintaan: maksimal 3 halaman hasil atau 10
  halaman produk per pertanyaan. Jangan merayapi seluruh kategori atau toko.
- Jangan login, jangan mengisi formulir, jangan menambahkan ke keranjang,
  dan jangan melakukan pembelian atau pembayaran.
- Jangan pernah mengarang harga, rating, atau stok. Bila data tidak terlihat,
  tulis "tidak tersedia".
- Harga dan stok bisa berubah; selalu sebutkan waktu pengambilan data.
- Jangan mengumpulkan data pribadi penjual atau pembeli (nomor telepon,
  alamat, ulasan yang menyebut nama orang).
```

## Notes

- Keep lookups small and on demand. Tokopedia's terms restrict automated bulk
  collection, so this agent is for ad-hoc product research, not scheduled
  scraping.
- The first `browser` call in a fresh container fetches the `agent-browser`
  CLI through npx. It needs outbound network access and adds a few seconds
  once.
- Chromium shares the container's 1 GB memory limit. Watch
  `sudo docker stats hermes-tokopedia` on the VM if pages fail to load.
- To render the same profile outside SSS, see the `tokopedia` entry in
  [../agents.example.yaml](../agents.example.yaml).
