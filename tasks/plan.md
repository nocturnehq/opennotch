# OpenNotch Soon settings

Implement each setting through the Settings window and the running X11 app. Use the NotchPixel screenshots, saved configuration and low-memory VM observations for the visible behavior. Keep desktop panels in place and exercise both Plasma and Cinnamon code paths.

## Implementation decisions

- Keep the current single timer, clipboard and notification state when adding more displays. Monitor-specific windows should reuse that state.
- Give captures and recordings a shared, user-owned save location. Use the existing Shelf for screenshot access and finish recordings safely before config reload or exit.
- Use the existing GTK stack for the Web tab and lazy-load an embedded browser. Treat the URL and chosen share file as explicit user inputs.
- Keep window manager-specific changes reversible. Use existing Plasma and Cinnamon integration points for Alt+Tab and wallpaper where they provide the needed behavior.
- Verify external services with test data before signing in or recording the user's real desktop. Use the installed packages and check upstream identity before adding dependencies.

## Work order

1. Capture tools and privacy state.
2. Embedded Web tab and shared display state.
3. Local file sharing and desktop video.
4. Taskbar and task switcher.
5. Calls, streaming and gaming.
6. Pet, language and agent completion.

The acceptance and testing checklist is in `todo.md`.
