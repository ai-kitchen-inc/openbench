/** Seal-style brand mark: double ring, shield with chat-bubble core and a
 * gold star. Monochrome-friendly (currentColor) with a gold accent so it
 * reads as an official emblem on both the navy sidebar and light surfaces. */
export function BrandMark({ size = 36 }: { size?: number }) {
  return (
    <span className="brand-mark" aria-hidden="true" style={{ width: size, height: size }}>
      <svg width={size} height={size} viewBox="0 0 48 48" fill="none">
        {/* Outer double ring */}
        <circle cx="24" cy="24" r="22" stroke="currentColor" strokeWidth="2.5" />
        <circle cx="24" cy="24" r="18" stroke="currentColor" strokeWidth="1" opacity="0.55" />
        {/* Shield */}
        <path
          d="M24 10.5 33.5 14v8.2c0 6.3-4 11.1-9.5 13.3-5.5-2.2-9.5-7-9.5-13.3V14L24 10.5z"
          stroke="currentColor"
          strokeWidth="2"
          strokeLinejoin="round"
        />
        {/* Chat bubble core */}
        <path
          d="M19 19.5h10a1.5 1.5 0 0 1 1.5 1.5v5a1.5 1.5 0 0 1-1.5 1.5h-4.5L21 30v-2.5h-2A1.5 1.5 0 0 1 17.5 26v-5a1.5 1.5 0 0 1 1.5-1.5z"
          stroke="currentColor"
          strokeWidth="1.6"
          strokeLinejoin="round"
        />
        {/* Gold star */}
        <path
          d="m24 2.8.9 1.9 2.1.3-1.5 1.5.4 2.1-1.9-1-1.9 1 .4-2.1-1.5-1.5 2.1-.3.9-1.9z"
          fill="#c39a3b"
        />
      </svg>
    </span>
  );
}
