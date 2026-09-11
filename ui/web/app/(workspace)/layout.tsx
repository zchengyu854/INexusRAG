import { SideNav } from "@/components/shell/side-nav"
import { TopStatusBar } from "@/components/shell/top-status-bar"

export default function WorkspaceLayout({ children }: { children: React.ReactNode }) {
  return (
    <div className="flex h-dvh w-full overflow-hidden">
      <SideNav />
      <div className="flex min-w-0 flex-1 flex-col">
        <TopStatusBar />
        <main className="min-h-0 min-w-0 flex-1 overflow-hidden">{children}</main>
      </div>
    </div>
  )
}
