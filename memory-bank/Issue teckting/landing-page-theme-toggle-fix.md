# Landing Page Theme Toggle Icon Fix Plan

## Problem Analysis
The landing page theme toggle icons (sun/moon) are disappearing because the toggle ball (handle) is physically covering them. This is the same issue we just fixed for the sidebar toggles.

## Root Cause
**Current CSS positioning in lines 1174-1200:**
- Toggle ball: `left: 0.2em`, `width: 1.1em` (spans from 0.2em to 1.3em)
- Sun icon: `left: 0.4em` (gets covered by the ball in light mode)
- Moon icon: `right: 0.4em` (gets covered by the ball in dark mode)

## Solution Strategy
Apply the same fix pattern used for sidebar toggles:
1. **Reposition icons** to avoid collision with toggle ball
2. **Use absolute positioning** with appropriate spacing
3. **Show inactive theme icon** as visual cue for available switch

## Required CSS Changes

### Update Icon Positioning (Lines 1184-1200)
```css
.theme-switch-label .sun-icon {
  left: 0.2em;    /* Move further left, away from ball */
  opacity: 0;     /* Hidden in light mode */
}

[data-bs-theme="dark"] .theme-switch-label .sun-icon {
  opacity: 1;     /* Visible in dark mode (when ball is on right) */
}

.theme-switch-label .moon-icon {
  right: 0.2em;   /* Move further right, away from ball */
  opacity: 1;     /* Visible in light mode */
}

[data-bs-theme="dark"] .theme-switch-label .moon-icon {
  opacity: 0;     /* Hidden in dark mode (when ball is on left) */
}
```

## Expected Behavior After Fix
- **Light Mode**: Moon icon visible on right side (shows user can switch to dark)
- **Dark Mode**: Sun icon visible on left side (shows user can switch to light)
- **No collision**: Icons positioned away from toggle ball path
- **Consistent UX**: Matches the fixed sidebar toggle behavior

## Implementation Steps
1. Switch to code mode
2. Apply the CSS positioning changes
3. Test on landing page
4. Verify theme switching works correctly
5. Ensure icons remain visible throughout transition

## Files to Modify
- `static/css/style.css` (lines 1184-1200)

## Testing Checklist
- [ ] Sun icon visible in dark mode
- [ ] Moon icon visible in light mode
- [ ] Icons don't disappear during toggle transition
- [ ] Toggle ball doesn't cover icons
- [ ] Theme switching works correctly
- [ ] Responsive behavior maintained