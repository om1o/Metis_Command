import { Metadata, Viewport } from 'next';
import { GeistSans } from 'geist/font/sans';
import { GeistMono } from 'geist/font/mono';
import './globals.css';
import PwaRegister from '@/components/pwa-register';

export const metadata: Metadata = {
  title: 'Metis Automate',
  description: 'Describe a task. Run it once or schedule it. Local-first.',
  manifest: '/manifest.webmanifest',
  applicationName: 'Metis',
  appleWebApp: {
    capable: true,
    title: 'Metis',
    statusBarStyle: 'black-translucent',
  },
  icons: {
    icon: '/metis-mark.png',
    apple: '/metis-mark.png',
  },
};

/* Lets env(safe-area-inset-*) work in WebViews / notched devices */
export const viewport: Viewport = {
  width: 'device-width',
  initialScale: 1,
  viewportFit: 'cover',
  themeColor: '#0a0612',
};

export default function RootLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return (
    <html
      lang="en"
      data-theme="dark"
      suppressHydrationWarning
      className={`${GeistSans.className} ${GeistMono.variable} antialiased`}
    >
      <body>
        <PwaRegister />
        {children}
      </body>
    </html>
  );
}
