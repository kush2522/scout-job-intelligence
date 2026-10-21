import "./globals.css";
import { AuthSessionProvider } from "@/components/auth-session-provider";
export const metadata = { title: "Scout — Job Intelligence", description: "Search jobs across company career pages and supported job sources." };
export default function RootLayout({children}:{children:React.ReactNode}) { return <html lang="en"><body><AuthSessionProvider>{children}</AuthSessionProvider></body></html>; }
