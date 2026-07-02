# File Support Plan: EPUB, Audio, Images, Video — Provider-Agnostic Multimodal

## Context

OpenBench's chat stack is **text-only end-to-end**. Uploads → extractor → `extracted_text`
→ LLM. The Gemini provider's `_convert_messages` builds text-only `Part`s; it never sends
image/audio/video bytes even though Gemini natively understands all three.

This blocks: **EPUB** (no extractor), **Audio** `.mp3 .wav .m4a .mp4-audio .ogg .aac .flac`
(placeholder only), **Images** `.gif .heic .tiff .bmp .svg` (only png/jpg/webp OCR'd),
**Video** `.mp4 .mov .avi` (placeholder only).

**Decisions:**

1. **Hybrid** — raw media bytes → model for true understanding **and** keep text
   transcript/OCR for search/RAG.
2. **Gemini native audio** for transcription now (no Whisper / no extra infra).
3. Scope = **SDK core + general-chat + frontend UI**.
4. **Provider-agnostic.** Gemini may later be swapped for open-source models (GLM, Qwen —
   OpenAI-API-compatible). No new Gemini-locked surface: media and transcription go behind
   provider-neutral abstractions; Gemini is the one concrete impl built now. Swapping later
   = register a new class, zero changes to extractors/engine/UI.

**Outcome:** upload a book/voice-note/screenshot/clip; the model sees/hears it natively
(when the active model supports that modality) and always has a searchable text version.
When the active model can't do a modality, the text track is the automatic fallback —
this is what makes the feature portable across models.

---

## Abstraction seams (verified in code)

- `LLMProvider` ABC — `core/abstractions.py:406`. `generate(prompt, model, **params)`;
  message format = OpenAI-style `list[dict]`. `_convert_messages` is **Gemini-only**
  (`llm_providers.py:122`) → the per-provider translation point.
- `Message` dataclass — `base.py:57`, has extensible `raw_content`. Add neutral `media`.
- Provider selection — `ProviderService.resolve(ProviderType.LLM, ...)`
  (`core/providers.py:350`); `BaseAgent._get_llm()` (`base.py:833`). Registry:
  `@LLMProviderRegistry.register("chat","gemini")` (`llm_providers.py:799`).
- `ProviderType.VOICE` enum **already reserved** (`providers.py:142`), no registry yet →
  home for transcription.
- `ModelInfo` flags (`config.py:48`) — informational only today; capability gate is new.

---

## Provider-neutral design

### 1. Neutral media representation
- `MediaContent` dataclass in `core/abstractions.py`: `{type, mime_type, path|uri|data,
  metadata}`.
- `media: list[MediaContent] | None` on `Message` (`base.py:57`), surfaced in
  `to_dict()`/`get_messages()`. Plain-string content stays valid (backward-compatible).
- `engine.py` (~540-558): besides `extracted_text`, attach media `Attachment`s
  (`type in {image,audio,video}` with readable `path`) as `MediaContent`. No Gemini types
  in engine.

### 2. Per-provider translation (only provider-specific code)
- `_convert_messages` is the provider contract: translate neutral `MediaContent` to SDK shape.
  - **Gemini (now):** small → `types.Part.from_bytes`; large (video/long audio) →
    `client.files.upload` → `types.Part.from_uri` (Files API >~20 MB). `_upload_via_files_api`
    with per-process cache keyed by file hash/id.
  - **OpenAI-compatible (future GLM/Qwen):** `{"type":"image_url","image_url":{...}}` /
    base64 data URLs. Documented target shape only — not built now.
- **Capability gate + degradation.** Add `supports_audio`/`supports_video` to `ModelInfo`;
  register Gemini 2.5-flash/2.5-pro/3-flash-preview with vision+audio+video. Send media
  natively only if the active model's flag is set; else drop to text track. Any send failure
  → log + fall back to `extracted_text`. Never hard-fail a turn over media.

### 3. Swappable transcription (no Gemini lock)
- `TranscriptionProvider` ABC in `core/abstractions.py`:
  `transcribe(audio: str|bytes, model="", **params) -> str`.
- `TranscriptionRegistry` in `registry.py`; resolve via `ProviderType.VOICE` through the
  existing `ProviderService`.
- `GeminiTranscriber` (concrete, registered) in `intelligence/transcription.py`.
- **Audio extractor depends on the abstract `TranscriptionProvider`**, resolved from config
  — never imports Gemini directly. Future Whisper/OpenAI transcriber = new class, zero
  extractor changes.

---

## Track 2 — Extractors (text/transcript for RAG + portable fallback)

Follow the `DoclingContentExtractor` shape
(`examples/general-chat/src/general_chat/extractor.py`); register in
`SourceParserRegistry.parse_file` (`sources.py:594-612`). Lazy imports inside functions.

- **EPUB** — `src/openbench/data/sources/epub.py` (`EPUBSource(DataSource)` mirroring
  `pdf.py`): `ebooklib` + `beautifulsoup4` → markdown per chapter. Wire into
  `FileContentExtractor` (`chat/files.py:240-343`) + general-chat registry.
- **Audio** — branch routes `audio/*` to the resolved `TranscriptionProvider`; transcript
  → `extracted_text`/`SourceRecord.text`.
- **Images** — extend `_IMAGE_MIME_TYPES`/`_IMAGE_EXTENSIONS` (`extractor.py:22-23`) +
  `IMAGE_*` (`sources.py`) for gif/heic/tiff/bmp/svg. New `src/openbench/utils/media.py`
  normalization: heic→jpeg (`pillow-heif`), tiff/bmp/gif→png (Pillow; gif first frame),
  svg→read XML text **and** rasterize→png (`cairosvg`). Existing `extract_image` OCR
  consumes the normalized raster.
- **Video** — branch for `video/*`; avi/mov transcode→mp4 via ffmpeg (`imageio-ffmpeg`)
  when the model rejects the container. Track-2 stores model-generated transcript+summary.
- **MIME whitelist + guess** — add new types to general-chat `server/app.py` whitelist
  (~51-67) and `_guess_mime_type()` (`chat/files.py:321-342`). Route slow video/long-audio
  extraction through the async worker (`gcp_worker.py`/Pub/Sub), not `/chat/upload`.

---

## Frontend UI (studio/chat-ui + general-chat frontend)

MIME-based already (provider-agnostic). Files: `ChatInput.tsx`, `AttachmentPreview.tsx`,
`ob-file-card.tsx`, `renderers/media.py` (Image/Video/AudioPlayer A2UI).

- Widen general-chat `acceptedFileTypes` → `image/*,audio/*,video/*,.epub` + docs;
  `maxUploadSize` prop + pre-send validation via `onAttachmentError`.
- Composer previews (Notion/monochrome, Lucide, no emojis): image thumbnail; audio inline
  `<audio>` + Music; video inline `<video>` + Film; epub → Book file card.
- Inline uploaded media in the stream (engine emits Image/Video/AudioPlayer); epub Book
  entry in `ob-file-card` MIME map.
- "transcribing…/analyzing…" indicator reusing the source "processing" status (`app.py`).

---

## Dependencies (pyproject extras)
- `[epub]` → `ebooklib`, `beautifulsoup4`
- `[media]` → `pillow-heif`, `cairosvg`, `imageio-ffmpeg`
- Transcription reuses the existing Gemini dep. VM image needs `ffmpeg`; note in
  `deploy/DEPLOY.md`.

---

## Microcommits (5)

1. **`feat: epub + extended image extraction`** — `epub.py`, `utils/media.py`, widen image
   MIME/ext, MIME whitelist + `_guess_mime_type`, `[epub]`/`[media]` extras. Pure Track-2.
   Tests: `test_epub_source.py`, `test_media_normalization.py`.
2. **`feat: provider-neutral multimodal message channel`** — `MediaContent` +
   `Message.media`, engine plumbing, Gemini `_convert_messages` translation + Files API,
   `ModelInfo` audio/video flags + gate + degradation. Tests: `test_gemini_multimodal.py`.
3. **`feat: swappable transcription + audio support`** — `TranscriptionProvider` ABC,
   `TranscriptionRegistry` + VOICE wiring, `GeminiTranscriber`, audio extractor branch.
   Tests: `test_transcription.py`.
4. **`feat: video understanding`** — transcode util, video extractor branch, async-worker
   routing. Tests: video MIME routing + transcode fallback.
5. **`feat: multimodal upload UI + docs`** — accept types, previews/players, `ob-file-card`
   epub, processing indicator, pyproject extras + `deploy/DEPLOY.md`. Tests: `pnpm vitest`.

---

## Verification

1. **Unit** (`python -m unittest discover tests -v`): the test files above + extend
   `test_sdk_skills.py`-style registry-contract checks.
2. **Portability check:** flip a model's `supports_audio/video` off, assert the turn still
   succeeds via the text track — proves no Gemini lock.
3. **Provider smoke** (real key, manual): image/audio/video understanding, not OCR stub.
4. **App E2E** (`examples/general-chat`, :8000 + frontend): upload one of each new type.
5. **Lint/type:** `ruff check src tests`, `mypy src/openbench`, `black --check`,
   `cd studio/chat-ui && pnpm tsc --noEmit && pnpm vitest`.
