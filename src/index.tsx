import { useState, useEffect, useRef } from "react";
import { definePlugin, routerHook } from "@decky/api";
import {
  staticClasses,
  afterPatch,
  findInReactTree,
  createReactTreePatcher,
  appDetailsClasses,
  Navigation,
  Focusable,
  DialogButton,
} from "@decky/ui";
import { FaDownload, FaSync, FaCog } from "react-icons/fa";
import { GameList } from "./pages/GameList";
import { GameDetail } from "./pages/GameDetail";
import { Settings } from "./pages/Settings";
import { Library } from "./pages/Library";
import { AppPageButton } from "./components/AppPageButton";
import { requestRefresh, subscribeRefreshing, getRefreshing } from "./refresh";
import {
  ROUTE_GAME_DETAIL,
  ROUTE_SETTINGS,
  ROUTE_LIBRARY,
} from "./routes";

// Compact icon button for the native title bar (titleView). Only the size is
// constrained; background/colour/focus stay native (Steam fills it white on
// focus), matching every other DialogButton.
const headerIconStyle = {
  minWidth: 0,
  width: "32px",
  height: "28px",
  padding: 0,
  display: "flex",
  alignItems: "center",
  justifyContent: "center",
  fontSize: "15px",
};

// Title-bar Refresh: re-checks component health + stuck updates (GameList's
// refreshStatus). Its FaSync spins while that runs — both on the manual press
// and on the initial load when the QAM opens — so the panel isn't just blank.
//
// The spin is driven by the Web Animations API (element.animate) on a wrapper
// span, NOT a CSS @keyframes. An injected <style> keyframe didn't apply in the
// QAM's document context (the icon never turned), so we animate the element
// directly — no global stylesheet, no transform-origin gotcha (the span is an
// HTML element, so it rotates about its own centre).
function RefreshButton() {
  const [spinning, setSpinning] = useState(getRefreshing());
  const spinRef = useRef<HTMLSpanElement | null>(null);
  const animRef = useRef<Animation | null>(null);
  useEffect(() => subscribeRefreshing(setSpinning), []);
  useEffect(() => {
    const el = spinRef.current;
    if (!el) return;
    if (spinning && !animRef.current) {
      animRef.current = el.animate(
        [{ transform: "rotate(0deg)" }, { transform: "rotate(360deg)" }],
        { duration: 1000, iterations: Infinity, easing: "linear" },
      );
    } else if (!spinning && animRef.current) {
      animRef.current.cancel();
      animRef.current = null;
    }
  }, [spinning]);
  return (
    <DialogButton style={headerIconStyle} onClick={() => requestRefresh()}>
      <span ref={spinRef} style={{ display: "inline-flex" }}>
        <FaSync />
      </span>
    </DialogButton>
  );
}

function patchLibraryApp() {
  return routerHook.addPatch("/library/app/:appid", (tree: any) => {
    const routeProps = findInReactTree(tree, (x: any) => x?.renderFunc);
    if (routeProps) {
      const patchHandler = createReactTreePatcher(
        [
          (tree: any) =>
            findInReactTree(
              tree,
              (x: any) => x?.props?.children?.props?.overview,
            )?.props?.children,
        ],
        (_: any[], ret: any) => {
          try {
            const container = findInReactTree(
              ret,
              (x: any) =>
                Array.isArray(x?.props?.children) &&
                x?.props?.className?.includes(appDetailsClasses.InnerContainer),
            );
            if (typeof container !== "object" || !container) {
              return ret;
            }
            // Avoid duplicate injection
            const alreadyInjected = container.props.children.some(
              (c: any) => c?.key === "qa-app-btn",
            );
            if (!alreadyInjected) {
              // Insert after the first child (header)
              container.props.children.splice(
                1,
                0,
                <AppPageButton key="qa-app-btn" />,
              );
            }
          } catch (e) {
            console.error("LumaDeck: library patch error", e);
          }
          return ret;
        },
      );
      afterPatch(routeProps, "renderFunc", patchHandler);
    }
    return tree;
  });
}

export default definePlugin(() => {
  // Register routes for sub-pages
  routerHook.addRoute(ROUTE_GAME_DETAIL + "/:appid", () => {
    const appid = parseInt(
      window.location.pathname.split("/").pop() || "0",
      10,
    );
    return <GameDetail appid={appid} />;
  });

  routerHook.addRoute(ROUTE_SETTINGS, () => <Settings />);
  routerHook.addRoute(ROUTE_LIBRARY, () => <Library />);

  // Patch library app detail page to show "Added via LumaDeck" badge
  const libraryPatch = patchLibraryApp();

  return {
    name: "LumaDeck",
    // Custom native title bar: brand on the left, utility icons on the right
    // (Refresh + Settings). This is the idiomatic Decky slot for header
    // actions, so they don't need a hand-built row inside the panel content.
    titleView: (
      // Idiomatic single-Focusable title bar: the title takes the slack
      // (flex:1) and pushes the icons to the right. Avoids the extra full-width
      // wrapper div, which was abutting the native back button and drawing a
      // dark seam on its right edge.
      <Focusable style={{ display: "flex", alignItems: "center", gap: "6px", width: "100%" }}>
        {/* flex:1 is layout only (pushes the icons to the right). No style
            override on the native title — its mask and drop shadow are kept
            exactly as Steam draws them (DESIGN_UI.md §0: title stays native). */}
        <div className={staticClasses.Title} style={{ flex: 1 }}>
          LumaDeck
        </div>
        <RefreshButton />
        <DialogButton
          style={headerIconStyle}
          onClick={() => Navigation.Navigate(ROUTE_SETTINGS)}
        >
          <FaCog />
        </DialogButton>
      </Focusable>
    ),
    content: <GameList />,
    icon: <FaDownload />,
    onDismount() {
      routerHook.removeRoute(ROUTE_GAME_DETAIL + "/:appid");
      routerHook.removeRoute(ROUTE_SETTINGS);
      routerHook.removeRoute(ROUTE_LIBRARY);
      routerHook.removePatch("/library/app/:appid", libraryPatch);
    },
  };
});
