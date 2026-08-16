import { withBase } from "@utils/url";

export const config = {
  name: "StateM",
  title: "StateM",
  description:
    "StateM is an agent-native state machine for long-horizon agents. It turns an execution graph into a runbook the agent operates from its own CLI: durable states, phase-local context, checked transitions, and versioned practices.",
  page_width: "64rem",

  // Repository and paper links, reused across the hero and the footer.
  // The header carries only the theme toggle; navigation lives in the page
  // itself (hero links, in-body links, and the left-margin outline).
  repo: "https://github.com/henryqin1997/statem",
  paper: withBase("/statem.pdf"),
  submission: "https://github.com/harbor-framework/terminal-bench-2-1/pull/142",
};
