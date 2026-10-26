/** Seal-style brand mark: double ring, shield with an "S" monogram core and a
 * gold star. Monochrome-friendly (currentColor) with a gold accent so it
 * reads as an official SSS emblem on both the navy sidebar and light
 * surfaces. */
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
        {/* "S" monogram core */}
        <path
          d="M27.6 19.4c-.8-1-2-1.6-3.6-1.6-2.2 0-3.8 1.2-3.8 3 0 4 7.6 2 7.6 6.2 0 1.9-1.7 3.2-4 3.2-1.8 0-3.2-.7-4-1.9"
          stroke="currentColor"
          strokeWidth="1.9"
          strokeLinecap="round"
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
