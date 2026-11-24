import { callable, definePlugin, toaster } from "@decky/api";
import {
  ButtonItem, ConfirmModal, DropdownItem, Field, PanelSection, PanelSectionRow,
  TextField, ToggleField, showModal,
} from "@decky/ui";
import { useEffect, useState } from "react";
import { FaGamepad } from "react-icons/fa";

declare const SteamClient: any;
declare const appStore: any;

type Game = { name: string; note: string; manual: boolean; enabled: boolean };
type Pad = { path: string; kind: string; battery?: { pct: number; charging: boolean } | null };
type State = {
  running: boolean; pads: Pad[]; auto: boolean; selected: string; games: Game[];
  perms: boolean; descriptor: boolean;
};

const getState = callable<[], State>("get_state");
const setAuto = callable<[boolean], boolean>("set_auto");
const selectGame = callable<[string], boolean>("select_game");
const setGameEnabled = callable<[string, boolean], boolean>("set_game_enabled");
const addManual = callable<[string], boolean>("add_manual");
const setRunning = callable<[boolean], boolean>("set_running");
const installPerms = callable<[], boolean>("install_perms");
const captureDescriptor = callable<[], string>("capture_descriptor");
const gameEvent = callable<[string, boolean], boolean>("game_event");

function AddGame({ closeModal, onAdd }: { closeModal?: () => void; onAdd: (n: string) => void }) {
  const [v, setV] = useState("");
  return (
    <ConfirmModal
      strTitle="Agregar juego manual"
      strDescription="Escribe el nombre del juego como aparece en Steam."
      strOKButtonText="Agregar"
      strCancelButtonText="Cancelar"
      onOK={() => { if (v.trim()) onAdd(v.trim()); closeModal?.(); }}
      onCancel={() => closeModal?.()}
    >
      <TextField value={v} onChange={(e) => setV(e.target.value)} />
    </ConfirmModal>
  );
}

function Content() {
  const [st, setSt] = useState<State | null>(null);
  const refresh = async () => { try { setSt(await getState()); } catch {} };

  useEffect(() => {
    refresh();
    const id = setInterval(refresh, 2000);
    return () => clearInterval(id);
  }, []);

  if (!st) return <PanelSection title="DS Bridge"><PanelSectionRow>Cargando…</PanelSectionRow></PanelSection>;

  const pad = st.pads[0];
  const cur = st.games.find((g) => g.name === st.selected) ?? st.games[0];
  const active = st.games.filter((g) => g.enabled).map((g) => g.name);

  return (
    <>
      <PanelSection title="Mando">
        <PanelSectionRow>
          <Field label={pad ? (pad.kind === "ds4" ? "DualShock 4" : "DualSense") : "Mando"} focusable>
            {pad ? "Bluetooth" : "No conectado"}
          </Field>
        </PanelSectionRow>
        {pad?.battery && (
          <PanelSectionRow>
            <Field label="Batería (aprox.)" focusable>
              {pad.battery.pct}%{pad.battery.charging ? " · cargando" : ""}
            </Field>
          </PanelSectionRow>
        )}
        <PanelSectionRow>
          <Field label="Mando virtual" focusable>{st.running ? "Activo" : "Inactivo"}</Field>
        </PanelSectionRow>
        <PanelSectionRow>
          <Field label="Steam Input" focusable>Desactívalo en el juego</Field>
        </PanelSectionRow>
      </PanelSection>

      <PanelSection title="Bridge">
        <PanelSectionRow>
          <ToggleField label="Activar al abrir juegos" description="Se apaga al volver a Steam"
            checked={st.auto} onChange={async (v) => { await setAuto(v); refresh(); }} />
        </PanelSectionRow>
      </PanelSection>

      <PanelSection title="Juegos">
        <PanelSectionRow>
          <DropdownItem label="Selección de juego"
            rgOptions={st.games.map((g) => ({ data: g.name, label: g.name }))}
            selectedOption={cur?.name}
            onChange={async (o) => { await selectGame(o.data); refresh(); }} />
        </PanelSectionRow>
        {cur && (
          <PanelSectionRow>
            <ToggleField label="Usar con este juego" description={cur.note}
              checked={cur.enabled}
              onChange={async (v) => { await setGameEnabled(cur.name, v); refresh(); }} />
          </PanelSectionRow>
        )}
        <PanelSectionRow>
          <Field label="Activos" focusable>{active.length ? active.join(", ") : "Ninguno"}</Field>
        </PanelSectionRow>
        <PanelSectionRow>
          <ButtonItem layout="below"
            onClick={() => showModal(<AddGame onAdd={async (n) => { await addManual(n); refresh(); }} />)}>
            Agregar juego manual
          </ButtonItem>
        </PanelSectionRow>
      </PanelSection>

      <PanelSection title="Audio del mando">
        <PanelSectionRow><Field label="Estado" focusable>En desarrollo</Field></PanelSectionRow>
      </PanelSection>

      <PanelSection title="Configuración">
        <PanelSectionRow>
          <ButtonItem layout="below" disabled={st.perms}
            onClick={async () => { await installPerms(); toaster.toast({ title: "DS Bridge", body: "Permisos instalados" }); refresh(); }}>
            {st.perms ? "Permisos instalados" : "Instalar permisos"}
          </ButtonItem>
        </PanelSectionRow>
        <PanelSectionRow>
          <ButtonItem layout="below" description="Conecta el mando por cable USB y pulsa."
            onClick={async () => { const o = await captureDescriptor(); toaster.toast({ title: "Descriptor", body: o.slice(0, 120) }); refresh(); }}>
            {st.descriptor ? "Descriptor capturado" : "Capturar descriptor USB"}
          </ButtonItem>
        </PanelSectionRow>
        <PanelSectionRow>
          <ToggleField label="Probar bridge ahora" checked={st.running}
            onChange={async (v) => { await setRunning(v); refresh(); }} />
        </PanelSectionRow>
      </PanelSection>
    </>
  );
}

export default definePlugin(() => {
  const reg = SteamClient.GameSessions.RegisterForAppLifetimeNotifications((u: any) => {
    const name: string = appStore.GetAppOverviewByAppID(u.unAppID)?.display_name ?? "";
    if (name) gameEvent(name, !!u.bRunning);
  });
  return {
    name: "DS Bridge",
    titleView: <div>DS Bridge</div>,
    content: <Content />,
    icon: <FaGamepad />,
    onDismount() { reg?.unregister?.(); },
  };
});
