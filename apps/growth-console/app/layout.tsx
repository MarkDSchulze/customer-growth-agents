import type { Metadata } from 'next';
import './globals.css';
export const metadata: Metadata = {title: 'Growth OS · Command Center', description: 'Governed customer growth orchestration'};
export default function RootLayout({children}: Readonly<{children: React.ReactNode}>) {
  return <html lang="en"><body>{children}</body></html>;
}
