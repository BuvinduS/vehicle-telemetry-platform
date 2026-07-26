import LiveDashboard from "@/components/LiveDashboard";
import ModeSwitcher from "@/components/ModeSwitcher";

export default function Home() {
  return (
    <main className="min-h-screen bg-bg text-ink p-8 flex flex-col gap-10">
      <ModeSwitcher />
      <LiveDashboard/>
    </main>
  );
}