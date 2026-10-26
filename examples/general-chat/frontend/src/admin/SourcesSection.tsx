import { BookIcon } from "../brand/icons";
import { SourceManager, type SourceManagerApi } from "../sources/SourceManager";
import {
  addTextSource,
  addUrlSource,
  deleteSource,
  listSources,
  uploadSourceFile,
} from "./sourcesApi";

const sharedSourcesApi: SourceManagerApi = {
  list: listSources,
  uploadFile: uploadSourceFile,
  addText: addTextSource,
  addUrl: addUrlSource,
  remove: deleteSource,
};

export function SourcesSection() {
  return (
    <section className="panel-section" aria-label="Sumber basis pengetahuan">
      <div className="panel-section__header">
        <div>
          <div className="panel-section__title">
            <BookIcon />
            Daftar Sumber
          </div>
          <div className="panel-section__subtitle">
            Unggah dokumen, tempel teks, atau tambahkan URL sebagai sumber resmi.
          </div>
        </div>
      </div>
      <div className="panel-section__body">
        <SourceManager
          api={sharedSourcesApi}
          emptyState={
            <div className="panel-empty">
              <span className="panel-empty__icon">
                <BookIcon size={20} />
              </span>
              <div className="panel-empty__title">Belum ada sumber</div>
              <div className="panel-empty__hint">
                Pengguna belum bisa mendapatkan jawaban sebelum Anda menambahkan minimal satu
                sumber. Unggah dokumen, tempel teks, atau tambahkan URL.
              </div>
            </div>
          }
        />
      </div>
    </section>
  );
}
