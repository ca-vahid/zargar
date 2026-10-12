import { savePref } from '../auth/storage';
import type { Workspace } from '../lib/books';
import { useStore } from '../store';

/** The side on screen. Until the person picks one it follows the server: a desk
 *  routing real orders opens on Live, otherwise on Practice. */
export function useWorkspace(): Workspace {
  return useStore((s) => s.workspace ?? ((s.settings['trading.mode'] ?? 'practice') === 'live' ? 'live' : 'practice'));
}

export function setWorkspace(workspace: Workspace) {
  // a book picked in the other workspace would not be in this one's list
  useStore.getState().set({ workspace, selectedBook: null });
  void savePref('workspace', workspace);
}
