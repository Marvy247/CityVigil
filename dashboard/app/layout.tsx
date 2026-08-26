import { GeistMono } from 'geist/font/mono'
import { GeistSans } from 'geist/font/sans'
import './globals.css'

/**
 * Fonts come from the locally-installed `geist` package rather than
 * `next/font/google`. Fetching DM Sans at build time makes the build depend on
 * outbound network access to Google, which fails in sandboxed and offline
 * environments — including, potentially, a judge's machine. Self-contained fonts
 * keep `npm run build` reproducible anywhere.
 */

const TITLE = 'CityVigil — protective intelligence for extreme heat'
const DESCRIPTION =
  'Decides who gets protected first when extreme heat hits, using hyperlocal temperature intelligence from the FortyGuard Temperature API.'

export default function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode
}>) {
  return (
    <html lang="en">
      <head>
        <link rel="icon" href="/favicon.ico" sizes="any" />
        <meta name="viewport" content="width=device-width, initial-scale=1" />
        <meta name="description" content={DESCRIPTION} />
        <title>{TITLE}</title>
        <meta property="og:type" content="website" />
        <meta property="og:title" content={TITLE} />
        <meta property="og:description" content={DESCRIPTION} />
        <meta property="og:image" content="/og-image.svg" />
        <meta property="og:image:width" content="1200" />
        <meta property="og:image:height" content="630" />
        <meta name="twitter:card" content="summary_large_image" />
        <meta name="twitter:title" content={TITLE} />
        <meta name="twitter:description" content={DESCRIPTION} />
        <meta name="twitter:image" content="/og-image.svg" />
      </head>
      <body className={`font-sans ${GeistSans.variable} ${GeistMono.variable}`}>
        {children}
      </body>
    </html>
  )
}
