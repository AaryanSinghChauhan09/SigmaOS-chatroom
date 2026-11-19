// SPDX-License-Identifier: MIT OR Apache-2.0
//! SigmaOS-chatroom — LAN chat server & client.
//!
//! Provides peer discovery, room management, message framing, and presence tracking
//! for ad-hoc local network communication.
//!
//! Inspired by Omarchy's decentralized peer-to-peer Unix tools, Hyprland's instant notification
//! popups, and the cozy Catppuccin Mocha chat styling.
//!
//! Principles: zero-dependency framing, bounded history buffers, pure `std`, zero `unsafe`.

#![forbid(unsafe_code)]

use std::collections::{HashMap, VecDeque};
use std::fmt;

// ── Error types ──────────────────────────────────────────────────────────────

#[derive(Debug, Clone, PartialEq, Eq)]
pub enum ChatError {
    InvalidNickname(String),
    RoomAlreadyExists(String),
    RoomNotFound(String),
    UserNotFound(String),
    EmptyMessage,
    MessageTooLarge(usize),
    UserBanned(String),
}

impl fmt::Display for ChatError {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        match self {
            Self::InvalidNickname(n) => write!(f, "invalid nickname: '{n}' (must be 1..32 alphanumeric/underscore)"),
            Self::RoomAlreadyExists(r) => write!(f, "room '{r}' already exists"),
            Self::RoomNotFound(r) => write!(f, "room '{r}' not found"),
            Self::UserNotFound(u) => write!(f, "user '{u}' not found"),
            Self::EmptyMessage => write!(f, "message content cannot be empty"),
            Self::MessageTooLarge(sz) => write!(f, "message size {sz} exceeds maximum 4096 bytes"),
            Self::UserBanned(u) => write!(f, "user '{u}' is banned from this room"),
        }
    }
}

impl std::error::Error for ChatError {}

// ── User & Presence ──────────────────────────────────────────────────────────

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum PresenceStatus {
    Online,
    Away,
    Busy,
    Offline,
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct ChatUser {
    pub nickname: String,
    pub status: PresenceStatus,
    pub address: String,
}

impl ChatUser {
    pub fn new(nickname: impl Into<String>, address: impl Into<String>) -> Result<Self, ChatError> {
        let nick = nickname.into().trim().to_string();
        if nick.is_empty() || nick.len() > 32 || !nick.chars().all(|c| c.is_alphanumeric() || c == '_' || c == '-') {
            return Err(ChatError::InvalidNickname(nick));
        }
        Ok(Self {
            nickname: nick,
            status: PresenceStatus::Online,
            address: address.into(),
        })
    }
}

// ── Messages & Framing ───────────────────────────────────────────────────────

#[derive(Debug, Clone, PartialEq, Eq)]
pub enum MessagePayload {
    Text(String),
    FileAnnouncement { filename: String, size_bytes: u64 },
    SystemNotice(String),
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct ChatMessage {
    pub id: u64,
    pub sender: String,
    pub payload: MessagePayload,
    pub timestamp_epoch_sec: u64,
}

impl ChatMessage {
    pub fn text(id: u64, sender: impl Into<String>, text: impl Into<String>) -> Result<Self, ChatError> {
        let content = text.into().trim().to_string();
        if content.is_empty() {
            return Err(ChatError::EmptyMessage);
        }
        if content.len() > 4096 {
            return Err(ChatError::MessageTooLarge(content.len()));
        }
        Ok(Self {
            id,
            sender: sender.into(),
            payload: MessagePayload::Text(content),
            timestamp_epoch_sec: 0,
        })
    }
}

// ── Chat Room ────────────────────────────────────────────────────────────────

#[derive(Debug, Clone)]
pub struct ChatRoom {
    pub name: String,
    pub topic: String,
    pub members: HashMap<String, ChatUser>,
    pub banned: Vec<String>,
    history: VecDeque<ChatMessage>,
    max_history: usize,
    next_msg_id: u64,
}

impl ChatRoom {
    pub fn new(name: impl Into<String>) -> Self {
        Self {
            name: name.into(),
            topic: String::new(),
            members: HashMap::new(),
            banned: Vec::new(),
            history: VecDeque::with_capacity(100),
            max_history: 100,
            next_msg_id: 1,
        }
    }

    pub fn join(&mut self, user: ChatUser) -> Result<(), ChatError> {
        if self.banned.contains(&user.nickname) {
            return Err(ChatError::UserBanned(user.nickname));
        }
        self.members.insert(user.nickname.clone(), user);
        Ok(())
    }

    pub fn leave(&mut self, nickname: &str) -> Option<ChatUser> {
        self.members.remove(nickname)
    }

    pub fn post_message(&mut self, sender: &str, content: &str) -> Result<u64, ChatError> {
        if !self.members.contains_key(sender) {
            return Err(ChatError::UserNotFound(sender.into()));
        }
        let msg = ChatMessage::text(self.next_msg_id, sender, content)?;
        let msg_id = msg.id;
        self.next_msg_id += 1;

        if self.history.len() >= self.max_history {
            self.history.pop_front();
        }
        self.history.push_back(msg);
        Ok(msg_id)
    }

    pub fn history(&self) -> &VecDeque<ChatMessage> {
        &self.history
    }
}

// ── Tests ────────────────────────────────────────────────────────────────────

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn valid_and_invalid_user_nickname() {
        // Arrange & Act
        let ok = ChatUser::new("alice_99", "192.168.1.10:9000");
        let invalid = ChatUser::new("bad name with spaces!", "192.168.1.10:9000");

        // Assert
        assert!(ok.is_ok());
        assert_eq!(ok.unwrap().status, PresenceStatus::Online);
        assert!(matches!(invalid, Err(ChatError::InvalidNickname(_))));
    }

    #[test]
    fn chat_room_join_and_leave() {
        // Arrange
        let mut room = ChatRoom::new("general");
        let user = ChatUser::new("bob", "192.168.1.20:9000").unwrap();

        // Act
        room.join(user.clone()).unwrap();
        assert_eq!(room.members.len(), 1);

        let left = room.leave("bob");

        // Assert
        assert_eq!(left, Some(user));
        assert!(room.members.is_empty());
    }

    #[test]
    fn banned_user_cannot_join() {
        // Arrange
        let mut room = ChatRoom::new("lobby");
        room.banned.push("troll".into());
        let user = ChatUser::new("troll", "192.168.1.50:9000").unwrap();

        // Act
        let err = room.join(user);

        // Assert
        assert_eq!(err, Err(ChatError::UserBanned("troll".into())));
    }

    #[test]
    fn message_posting_and_history_buffering() {
        // Arrange
        let mut room = ChatRoom::new("rust-chat");
        let user = ChatUser::new("charlie", "127.0.0.1:9000").unwrap();
        room.join(user).unwrap();

        // Act
        let id1 = room.post_message("charlie", "Hello SigmaOS!").unwrap();
        let id2 = room.post_message("charlie", "How is everyone?").unwrap();

        // Assert
        assert_eq!(id1, 1);
        assert_eq!(id2, 2);
        assert_eq!(room.history().len(), 2);
        assert_eq!(room.history()[0].sender, "charlie");
    }

    #[test]
    fn reject_empty_message() {
        // Arrange
        let mut room = ChatRoom::new("main");
        let user = ChatUser::new("dave", "127.0.0.1:9000").unwrap();
        room.join(user).unwrap();

        // Act
        let err = room.post_message("dave", "   ");

        // Assert
        assert_eq!(err, Err(ChatError::EmptyMessage));
    }

    #[test]
    fn error_display_formatting() {
        // Arrange
        let err = ChatError::RoomNotFound("random".into());
        // Act & Assert
        assert_eq!(format!("{err}"), "room 'random' not found");
    }
}
