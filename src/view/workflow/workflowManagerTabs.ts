/**
 * The Workflows panel's tab labels (launch-readiness ticket 41).
 *
 * The panel used to stack four sections in one column — New Workflow, Save
 * Current, Saved Workflows, Examples — so finding either of the two things a
 * reader actually browses (their own workflows, or the shipped gallery) meant
 * scrolling past the other three. The owner's fix was tabs: *Saved* ·
 * *Examples* · a third for the rest.
 *
 * The third is **New**, not a fourth word: "New Workflow" and "Save Current"
 * both act on the workflow currently open in the editor rather than browsing
 * a list, so they share a tab. Three tabs, not four — a "Save" tab holding
 * one button beside a "New" tab holding a form is a split with no reader
 * benefit, and the settled lexicon (package / template / instance / slug)
 * gains no new word here.
 *
 * Pinned so the labels do not drift silently — a string in JSX has no way to
 * fail on its own.
 */
export type WorkflowManagerTabId = 'new' | 'saved' | 'examples';

export interface WorkflowManagerTab {
  id: WorkflowManagerTabId;
  label: string;
}

export const WORKFLOW_MANAGER_TABS: readonly WorkflowManagerTab[] = [
  { id: 'new', label: 'New' },
  { id: 'saved', label: 'Saved' },
  { id: 'examples', label: 'Examples' },
];

export const DEFAULT_WORKFLOW_MANAGER_TAB: WorkflowManagerTabId = 'saved';
