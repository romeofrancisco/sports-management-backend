# Real-Time Game Scoring System

This document explains the real-time scoring system implemented for the sports management application.

## Overview

The real-time scoring system uses Django Channels WebSockets to provide live updates of game scores and status changes to **viewers** of games. The scoring interface itself doesn't need real-time updates since only the scorer has access to it and can see their own updates immediately.

**Key Point**: The real-time system is designed for **GameCard components** (viewed by spectators, coaches, players, etc.) to show live score updates, not for the ScoreBoard component in the scoring interface.

## Backend Implementation

### 1. WebSocket Consumer (`games/consumers.py`)
- **GameScoreConsumer**: Handles WebSocket connections for individual games
- **Connection URL**: `ws/games/{game_id}/`
- **Authentication**: Uses JWT token authentication via cookies
- **Authorization**: Checks user permissions based on their role (Admin, Coach, Player)

### 2. WebSocket Routing (`games/routing.py`)
- Defines URL patterns for game WebSocket connections
- Integrated with main ASGI routing in `sports_management/asgi.py`

### 3. Signals (`games/signals.py`)
- **update_game_score**: Triggered when PlayerStat is created/updated/deleted
- **handle_game_status_change**: Triggered when game status changes
- **Functions**:
  - `send_score_update()`: Broadcasts score changes to all connected clients
  - `send_game_status_update()`: Broadcasts status changes (start, complete, period changes)

### 4. Views Integration (`games/views.py`)
- Updated `update_scores()` method to send WebSocket updates
- Updated `manage()` method to send status updates for game actions (start, complete, next_period)

## Frontend Implementation

### 1. WebSocket Hook (`hooks/useGameScoreWebSocket.js`)
- **useGameScoreWebSocket**: Custom React hook for managing WebSocket connections
- **Features**:
  - Automatic connection/reconnection with exponential backoff
  - React Query cache updates for immediate UI consistency
  - Redux store updates for game state management
  - Custom callback support for score and status updates

### 2. Component Integration

#### GameCard (`components/games/GameCard.jsx`) - **Primary Target**
- **Real-time WebSocket connection for live games only**
- Local state management for real-time updates
- Visual animations for score changes
- Score update notifications
- Connection status indicators
- **Purpose**: Shows real-time updates to viewers/spectators

#### ScoreBoard (`pages/admin/game/components/scoring/ScoreBoard.jsx`) - **Scorer Interface**
- **No WebSocket connection needed**
- Uses Redux state for immediate local updates
- Simple score display with basic animations
- **Purpose**: Interface for the person recording the game (scorer only)

## Data Flow

1. **Score Update Trigger**:
   ```
   PlayerStat created/updated → Signal → Game.update_scores() → WebSocket broadcast
   ```

2. **Status Update Trigger**:
   ```
   Game action (start/complete/next_period) → Signal → WebSocket broadcast
   ```

3. **Frontend Reception**:
   ```
   WebSocket message → Hook processing → React Query cache → Redux store → UI update
   ```

## Message Types

### Score Update Message
```json
{
  "type": "score_update",
  "game_id": 123,
  "home_team_score": 45,
  "away_team_score": 38,
  "home_team_id": 1,
  "away_team_id": 2,
  "home_team_name": "Lakers",
  "away_team_name": "Warriors",
  "status": "in_progress",
  "current_period": 2,
  "timestamp": "2025-06-21T10:30:00Z"
}
```

### Status Update Message
```json
{
  "type": "game_status_update",
  "game_id": 123,
  "status": "completed",
  "current_period": 4,
  "started_at": "2025-06-21T09:00:00Z",
  "ended_at": "2025-06-21T11:00:00Z",
  "timestamp": "2025-06-21T11:00:00Z"
}
```

## Security

- **Authentication**: JWT token-based authentication
- **Authorization**: Role-based access control
  - Admins: Access to all games
  - Coaches: Access to their team's games or assigned games
  - Players: Access to their team's games
  - Others: Access to public games (configurable)

## Performance Considerations

- WebSocket connections only established for live games
- Automatic reconnection with exponential backoff
- Efficient React Query cache updates to prevent unnecessary re-renders
- Group-based broadcasting to minimize server load

## Testing

To test the real-time scoring system:

1. Start a game and navigate to the scoring interface
2. Open the same game in multiple browser tabs/windows
3. Record stats in one interface
4. Observe immediate score updates in all other interfaces
5. Verify connection status indicators work correctly

## Future Enhancements

- Real-time play-by-play updates
- Live game statistics beyond just scores
- Spectator mode for public game viewing
- Mobile push notifications for score updates
- Historical playback of game events
