'use client'

export function CityVigilLogo({ size = 40 }: { size?: number }) {
  return (
    <svg
      width={size}
      height={size}
      viewBox="0 0 64 64"
      fill="none"
      xmlns="http://www.w3.org/2000/svg"
      aria-hidden="true"
    >
      <defs>
        <linearGradient id="cv-gradient" x1="0%" y1="0%" x2="100%" y2="100%">
          <stop offset="0%" stopColor="#0ea5e9" />
          <stop offset="50%" stopColor="#06b6d4" />
          <stop offset="100%" stopColor="#22d3ee" />
        </linearGradient>
        <filter id="cv-glow" x="-50%" y="-50%" width="200%" height="200%">
          <feDropShadow dx="0" dy="2" stdDeviation="4" floodColor="#0ea5e9" floodOpacity="0.3" />
        </filter>
      </defs>

      {/* Outer shield shape */}
      <path
        d="M32 4 C16.5 4 4 16.5 4 32 C4 47.5 16.5 60 32 60 C47.5 60 60 47.5 60 32 C60 16.5 47.5 4 32 4 Z"
        fill="url(#cv-gradient)"
        filter="url(#cv-glow)"
      />

      {/* Inner shield - negative space */}
      <path
        d="M32 10 C20.3 10 11 19.3 11 31 C11 42.7 20.3 52 32 52 C43.7 52 53 42.7 53 31 C53 19.3 43.7 10 32 10 Z"
        fill="#f8fafc"
      />

      {/* Temperature wave pattern */}
      <g fill="none" stroke="url(#cv-gradient)" strokeWidth="2.5" strokeLinecap="round">
        <path d="M20 28 Q26 22 32 28 Q38 34 44 28" />
        <path d="M18 36 Q25 30 32 36 Q39 42 46 36" strokeWidth="2" opacity="0.7" />
        <path d="M20 44 Q26 38 32 44 Q38 50 44 44" strokeWidth="1.5" opacity="0.5" />
      </g>

      {/* Central alert/protection dot */}
      <circle cx="32" cy="36" r="4" fill="#0ea5e9" />
      <circle cx="32" cy="36" r="2" fill="#f8fafc" />

      {/* Subtle shield highlight */}
      <path
        d="M20 22 Q32 16 44 22"
        stroke="rgba(255,255,255,0.3)"
        strokeWidth="1.5"
        fill="none"
        strokeLinecap="round"
      />
    </svg>
  )
}

export function CityVigilWordmark({ size = 24 }: { size?: number }) {
  return (
    <svg
      width={size * 4}
      height={size}
      viewBox="0 0 200 48"
      fill="none"
      xmlns="http://www.w3.org/2000/svg"
      aria-hidden="true"
    >
      <defs>
        <linearGradient id="cv-text-gradient" x1="0%" y1="0%" x2="100%" y2="0%">
          <stop offset="0%" stopColor="#0ea5e9" />
          <stop offset="50%" stopColor="#06b6d4" />
          <stop offset="100%" stopColor="#22d3ee" />
        </linearGradient>
      </defs>
      <text
        x="0"
        y="36"
        fontFamily="system-ui, -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif"
        fontSize="40"
        fontWeight="700"
        fill="url(#cv-text-gradient)"
        letterSpacing="-0.5"
      >
        CityVigil
      </text>
    </svg>
  )
}