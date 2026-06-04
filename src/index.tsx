import { definePlugin, routerHook } from "@decky/api";
import {
  staticClasses,
  afterPatch,
  findInReactTree,
  createReactTreePatcher,
  appDetailsClasses,
} from "@decky/ui";
import { FaDownload } from "react-icons/fa";
import { GameList } from "./pages/GameList";
import { GameDetail } from "./pages/GameDetail";
import { Settings } from "./pages/Settings";
import { Downloads } from "./pages/Downloads";
import { AppPageButton } from "./components/AppPageButton";
import { ROUTE_GAME_DETAIL, ROUTE_SETTINGS, ROUTE_DOWNLOADS } from "./routes";

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
  routerHook.addRoute(ROUTE_DOWNLOADS, () => <Downloads />);

  // Patch library app detail page to show "Added via DeckTools" badge
  const libraryPatch = patchLibraryApp();

  return {
    name: "LumaDeck",
    title: <div className={staticClasses.Title}>LumaDeck</div>,
    content: <GameList />,
    icon: <FaDownload />,
    onDismount() {
      routerHook.removeRoute(ROUTE_GAME_DETAIL + "/:appid");
      routerHook.removeRoute(ROUTE_SETTINGS);
      routerHook.removeRoute(ROUTE_DOWNLOADS);
      routerHook.removePatch("/library/app/:appid", libraryPatch);
    },
  };
});
