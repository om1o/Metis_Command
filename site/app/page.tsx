import Hero from "./components/Hero";
import FeatureGrid from "./components/FeatureGrid";
import Logos from "./components/Logos";
import Footer from "./components/Footer";

export default function Page() {
  return (
    <main className="relative z-10">
      <Hero />
      <FeatureGrid />
      <Logos />
      <Footer />
    </main>
  );
}
