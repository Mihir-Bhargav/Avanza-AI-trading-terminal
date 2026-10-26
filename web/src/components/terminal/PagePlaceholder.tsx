import { Panel } from "../Panel";
import { StateView } from "../StateView";

/** Temporary body for terminal pages that are still being built. */
export function PagePlaceholder({ title, job }: { title: string; job: string }) {
  return (
    <div className="flex flex-1 flex-col gap-4 px-6 py-5">
      <h1 className="m-0 text-lg font-semibold text-text">{title}</h1>
      <Panel className="flex-1 items-center justify-center">
        <StateView kind="info" mood="thinking" title="Page in progress" message={job} />
      </Panel>
    </div>
  );
}
