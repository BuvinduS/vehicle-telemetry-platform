import ArcGauge from "@/components/ArcGauge";
import ModeSwitcher from "@/components/ModeSwitcher";
import NumericReadout from "@/components/NumericReadout";

export default function Home() {
  return (
    <main className="min-h-screen bg-bg text-ink p-8 flex flex-col gap-10">
      <ModeSwitcher />
      <div className="flex justify-center items-center gap-12 flex-1">
        <div className="flex flex-col gap-4">
          <NumericReadout label="Throttle" value={62} unit="%" warnAt={85} />
          <NumericReadout label="Engine Load" value={78} unit="%" warnAt={70} dangerAt={90} />
        </div>
        <ArcGauge label="Speed" value={180} min={0} max={220} unit="km/h" size={380} />
        <ArcGauge label="Engine" value={5200} min={0} max={7000} redline={6000} unit="rpm" size={380} />
      </div>
    </main>
  );
}