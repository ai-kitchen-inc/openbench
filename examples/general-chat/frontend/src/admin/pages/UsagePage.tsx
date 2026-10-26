import { useCallback, useEffect, useState } from "react";
import {
  getAdminUsage,
  getPricing,
  getQuotas,
  putPricing,
  putQuotas,
  readErrorMessage,
  type AdminUsage,
  type PricingState,
  type QuotasState,
} from "../../account/api";
import { useToast } from "../../Toast";
import { COMMON } from "../../i18n/id";

function formatUsd(value: number): string {
  return `$${value.toFixed(value >= 1 ? 2 : 4)}`;
}

function formatTokens(value: number): string {
  return value.toLocaleString("id-ID");
}

export function UsagePage() {
  const { show: showToast } = useToast();
  const [usage, setUsage] = useState<AdminUsage | null>(null);
  const [pricing, setPricing] = useState<PricingState | null>(null);
  const [quotas, setQuotas] = useState<QuotasState | null>(null);
  const [month, setMonth] = useState("");
  const [isLoading, setIsLoading] = useState(true);
  const [loadError, setLoadError] = useState("");
  const [isSaving, setIsSaving] = useState(false);
  const [rateDrafts, setRateDrafts] = useState<Record<string, string>>({});
  const [quotaDraft, setQuotaDraft] = useState("");
  const [overrideEmail, setOverrideEmail] = useState("");
  const [overrideLimit, setOverrideLimit] = useState("");

  const load = useCallback(async (selectedMonth?: string) => {
    setIsLoading(true);
    setLoadError("");
    try {
      const [usageData, pricingData, quotasData] = await Promise.all([
        getAdminUsage(selectedMonth),
        getPricing(),
        getQuotas(),
      ]);
      setUsage(usageData);
      setMonth(usageData.month);
      setPricing(pricingData);
      setQuotas(quotasData);
      setQuotaDraft(String(quotasData.defaultMonthlyTokens));
      const drafts: Record<string, string> = {};
      for (const [model, rates] of Object.entries(pricingData.models)) {
        drafts[`${model}.input`] = String(rates.input_per_1m);
        drafts[`${model}.output`] = String(rates.output_per_1m);
      }
      setRateDrafts(drafts);
    } catch (error) {
      setLoadError(readErrorMessage(error));
    } finally {
      setIsLoading(false);
    }
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  const saveRate = useCallback(
    async (model: string) => {
      const input = Number.parseFloat(rateDrafts[`${model}.input`] ?? "");
      const output = Number.parseFloat(rateDrafts[`${model}.output`] ?? "");
      if (Number.isNaN(input) || Number.isNaN(output) || input < 0 || output < 0) {
        showToast("Harga harus berupa angka >= 0.", "error");
        return;
      }
      setIsSaving(true);
      try {
        const resolved = await putPricing({
          models: { [model]: { input_per_1m: input, output_per_1m: output } },
        });
        setPricing(resolved);
        showToast(`Harga ${model} disimpan.`, "success");
      } catch (error) {
        showToast(`Gagal menyimpan harga: ${readErrorMessage(error)}`, "error");
      } finally {
        setIsSaving(false);
      }
    },
    [rateDrafts, showToast],
  );

  const saveQuotas = useCallback(
    async (patch: Partial<QuotasState>, label: string) => {
      setIsSaving(true);
      try {
        const resolved = await putQuotas(patch);
        setQuotas(resolved);
        setQuotaDraft(String(resolved.defaultMonthlyTokens));
        showToast(`${label} disimpan.`, "success");
      } catch (error) {
        showToast(`Gagal menyimpan ${label}: ${readErrorMessage(error)}`, "error");
      } finally {
        setIsSaving(false);
      }
    },
    [showToast],
  );

  const addOverride = useCallback(() => {
    if (!quotas) return;
    const email = overrideEmail.trim().toLowerCase();
    const limit = Number.parseInt(overrideLimit, 10);
    if (!email || Number.isNaN(limit) || limit < 0) {
      showToast("Isi email dan batas token (angka >= 0).", "error");
      return;
    }
    setOverrideEmail("");
    setOverrideLimit("");
    void saveQuotas(
      { overrides: { ...quotas.overrides, [email]: limit } },
      `Kuota ${email}`,
    );
  }, [overrideEmail, overrideLimit, quotas, saveQuotas, showToast]);

  const removeOverride = useCallback(
    (email: string) => {
      if (!quotas) return;
      const next = { ...quotas.overrides };
      delete next[email];
      void saveQuotas({ overrides: next }, `Kuota ${email}`);
    },
    [quotas, saveQuotas],
  );

  if (isLoading) {
    return <div className="sources-list__empty">{COMMON.loading}</div>;
  }

  if (loadError || !usage || !pricing || !quotas) {
    return (
      <div className="sources-list__empty">
        Gagal memuat penggunaan: {loadError}{" "}
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
          Pemakaian token dan biaya per pengguna, tabel harga model, serta kuota bulanan
          (hanya peringatan — tidak pernah memblokir).
        </div>
      </div>

      <section className="panel-section" aria-label="Penggunaan per pengguna">
        <div className="panel-section__header">
          <div>
            <div className="panel-section__title">Penggunaan per Pengguna</div>
            <div className="panel-section__subtitle">
              Total {formatTokens(usage.totals.totalTokens)} token ·{" "}
              {formatUsd(usage.totals.costUsd)} · {formatTokens(usage.totals.calls)}{" "}
              panggilan
            </div>
          </div>
          <input
            type="month"
            aria-label="Bulan"
            value={month}
            onChange={(event) => {
              setMonth(event.target.value);
              void load(event.target.value);
            }}
          />
        </div>
        <div className="panel-section__body">
          {usage.users.length === 0 ? (
            <div className="sources-list__empty">Belum ada pemakaian pada bulan ini.</div>
          ) : (
            <div className="sources-list">
              {usage.users.map((user) => (
                <div className="source-row" key={user.owner}>
                  <span
                    className={`source-row__badge${user.quota.warning ? "" : " source-row__badge--filled"}`}
                  >
                    {user.quota.warning ? "kuota!" : "ok"}
                  </span>
                  <div className="source-row__main">
                    <div className="source-row__name">{user.owner}</div>
                    <div className="source-row__meta">
                      {formatTokens(user.totalTokens)} token (
                      {formatTokens(user.promptTokens)} masuk /{" "}
                      {formatTokens(user.completionTokens)} keluar) ·{" "}
                      {formatUsd(user.costUsd)} · {formatTokens(user.calls)} panggilan
                      {user.quota.limit > 0
                        ? ` · kuota ${formatTokens(user.quota.used)}/${formatTokens(user.quota.limit)}`
                        : ""}
                    </div>
                  </div>
                </div>
              ))}
            </div>
          )}
        </div>
      </section>

      <section className="panel-section" aria-label="Harga model">
        <div className="panel-section__header">
          <div>
            <div className="panel-section__title">Harga Model</div>
            <div className="panel-section__subtitle">
              USD per 1 juta token. Biaya dihitung dengan tarif saat pemakaian terjadi.
            </div>
          </div>
        </div>
        <div className="panel-section__body">
          <div className="cap-group">
            {Object.keys(pricing.models)
              .sort()
              .map((model) => (
                <div className="cap-row settings-model-row" key={model}>
                  <div className="cap-row__main">
                    <div className="cap-row__label">{model}</div>
                    <div className="cap-row__desc">Masuk / keluar per 1 juta token</div>
                  </div>
                  <input
                    className="settings-model-select"
                    type="number"
                    min={0}
                    step="0.01"
                    aria-label={`Harga masuk ${model}`}
                    value={rateDrafts[`${model}.input`] ?? ""}
                    disabled={isSaving}
                    onChange={(event) =>
                      setRateDrafts((prev) => ({
                        ...prev,
                        [`${model}.input`]: event.target.value,
                      }))
                    }
                    onBlur={() => void saveRate(model)}
                  />
                  <input
                    className="settings-model-select"
                    type="number"
                    min={0}
                    step="0.01"
                    aria-label={`Harga keluar ${model}`}
                    value={rateDrafts[`${model}.output`] ?? ""}
                    disabled={isSaving}
                    onChange={(event) =>
                      setRateDrafts((prev) => ({
                        ...prev,
                        [`${model}.output`]: event.target.value,
                      }))
                    }
                    onBlur={() => void saveRate(model)}
                  />
                </div>
              ))}
          </div>
        </div>
      </section>

      <section className="panel-section" aria-label="Kuota bulanan">
        <div className="panel-section__header">
          <div>
            <div className="panel-section__title">Kuota Bulanan</div>
            <div className="panel-section__subtitle">
              0 = tanpa batas. Melampaui kuota hanya menampilkan peringatan.
            </div>
          </div>
        </div>
        <div className="panel-section__body">
          <div className="cap-group">
            <div className="cap-row settings-model-row">
              <div className="cap-row__main">
                <div className="cap-row__label">Kuota bawaan (token/bulan)</div>
                <div className="cap-row__desc">Berlaku untuk semua pengguna tanpa pengecualian.</div>
              </div>
              <input
                className="settings-model-select"
                type="number"
                min={0}
                aria-label="Kuota bawaan"
                value={quotaDraft}
                disabled={isSaving}
                onChange={(event) => setQuotaDraft(event.target.value)}
                onBlur={() => {
                  const parsed = Number.parseInt(quotaDraft, 10);
                  if (Number.isNaN(parsed) || parsed < 0) {
                    setQuotaDraft(String(quotas.defaultMonthlyTokens));
                    showToast("Kuota harus berupa angka >= 0.", "error");
                    return;
                  }
                  if (parsed !== quotas.defaultMonthlyTokens) {
                    void saveQuotas({ defaultMonthlyTokens: parsed }, "Kuota bawaan");
                  }
                }}
              />
            </div>
            {Object.entries(quotas.overrides).map(([email, limit]) => (
              <div className="cap-row" key={email}>
                <div className="cap-row__main">
                  <div className="cap-row__label">{email}</div>
                  <div className="cap-row__desc">{formatTokens(limit)} token/bulan</div>
                </div>
                <button
                  type="button"
                  className="panel-button"
                  disabled={isSaving}
                  onClick={() => removeOverride(email)}
                >
                  {COMMON.remove}
                </button>
              </div>
            ))}
          </div>
          <form
            className="sources-form"
            onSubmit={(event) => {
              event.preventDefault();
              addOverride();
            }}
          >
            <div className="sources-form__row">
              <input
                type="email"
                placeholder="email@perusahaan.co.id"
                aria-label="Email pengecualian"
                value={overrideEmail}
                onChange={(event) => setOverrideEmail(event.target.value)}
              />
              <input
                type="number"
                min={0}
                placeholder="Batas token"
                aria-label="Batas token pengecualian"
                value={overrideLimit}
                onChange={(event) => setOverrideLimit(event.target.value)}
              />
              <button
                type="submit"
                className="panel-button panel-button--primary"
                disabled={isSaving}
              >
                Tambah pengecualian
              </button>
            </div>
          </form>
        </div>
      </section>
    </>
  );
}
