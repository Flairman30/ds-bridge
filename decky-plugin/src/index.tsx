import { callable, definePlugin, toaster } from "@decky/api";
import { ButtonItem, PanelSection, PanelSectionRow, ToggleField } from "@decky/ui";
import { useEffect, useState } from "react";
import { FaGamepad } from "react-icons/fa";

type Status = {
  running: boolean;
  pads: { path: string; kind: string }[];
  perms: boolean;
  desc_ds4: boolean;
  desc_ds5: boolean;
};

const getStatus = callable<[], Status>("get_status");
const setEnabled = callable<[boolean], Status>("set_enabled");
const installPerms = callable<[], boolean>("install_perms");
const captureDescriptor = callable<[], string>("capture_descriptor");

function Content() {
  const [st, setSt] = useState<Status | null>(null);

  useEffect(() => {
    let alive = true;
    const tick = async () => { try { const s = await getStatus(); if (alive) setSt(s); } catch {} };
    tick();
    const id = setInterval(tick, 2000);
    return () => { alive = false; clearInterval(id); };
  }, []);

  if (!st) return <PanelSection title="DS Bridge"><PanelSectionRow>Cargando…</PanelSectionRow></PanelSection>;

  return (
    <>
      <PanelSection title="Bridge">
        <PanelSectionRow>
          <ToggleField label="Activar bridge" checked={st.running}
            onChange={async (v) => setSt(await setEnabled(v))} />
        </PanelSectionRow>
        <PanelSectionRow>
          Mandos: {st.pads.length ? st.pads.map((p) => p.kind.toUpperCase()).join(", ") : "ninguno"}
        </PanelSectionRow>
      </PanelSection>
      <PanelSection title="Configuración (una vez)">
        <PanelSectionRow>
          <ButtonItem layout="below" disabled={st.perms}
            onClick={async () => { await installPerms(); toaster.toast({ title: "DS Bridge", body: "Permisos instalados" }); setSt(await getStatus()); }}>
            {st.perms ? "Permisos instalados ✓" : "Instalar permisos"}
          </ButtonItem>
        </PanelSectionRow>
        <PanelSectionRow>
          <ButtonItem layout="below"
            description="Conecta el mando por cable USB y pulsa."
            onClick={async () => { const out = await captureDescriptor(); toaster.toast({ title: "Descriptor", body: out.slice(0, 120) }); setSt(await getStatus()); }}>
            Capturar descriptor USB {st.desc_ds4 || st.desc_ds5 ? "✓" : ""}
          </ButtonItem>
        </PanelSectionRow>
      </PanelSection>
    </>
  );
}

export default definePlugin(() => ({
  name: "DS Bridge",
  titleView: <div>DS Bridge</div>,
  content: <Content />,
  icon: <FaGamepad />,
  onDismount() {},
}));
