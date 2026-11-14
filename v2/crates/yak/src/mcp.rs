//! The read-only MCP server. Stage 1 plan, task 10.

use std::path::{Path, PathBuf};

use rmcp::model::{
    CallToolRequestParams, CallToolResponse, CallToolResult, ContentBlock, ErrorCode, JsonObject,
    ListToolsResult, PaginatedRequestParams, ServerCapabilities, ServerConfig, Tool,
    ToolAnnotations,
};
use rmcp::service::RequestContext;
use rmcp::{ErrorData, RoleServer, ServerHandler, ServiceExt};
use room::{ItemId, Room};
use serde_json::{Value, json};

use crate::{View, one_line, read_view};

/// Serve an existing room. No writing connection or writer lock is ever acquired.
pub async fn serve(dir: &Path) -> Result<(), Box<dyn std::error::Error>> {
    drop(Room::open_read_only(dir)?);
    let service = Reader {
        dir: dir.to_path_buf(),
    }
    .serve(rmcp::transport::stdio())
    .await?;
    service.waiting().await?;
    Ok(())
}

struct Reader {
    dir: PathBuf,
}

fn tools() -> Vec<Tool> {
    [
        (
            "room_status",
            "Read the room's current counts and turn ceiling",
        ),
        (
            "item_list",
            "List the room's items, with their current states",
        ),
        ("item_show", "Read one item by id"),
        ("disagreements", "List the room's disagreements"),
    ]
    .into_iter()
    .map(|(name, description)| {
        let mut schema = JsonObject::new();
        schema.insert("type".into(), json!("object"));
        schema.insert("additionalProperties".into(), json!(false));
        if name == "item_show" {
            schema.insert("properties".into(), json!({"id":{"type":"string"}}));
            schema.insert("required".into(), json!(["id"]));
        } else {
            schema.insert("properties".into(), json!({}));
        }
        Tool::new(name, description, schema)
            .with_annotations(ToolAnnotations::new().read_only(true).open_world(false))
    })
    .collect()
}

impl ServerHandler for Reader {
    fn get_info(&self) -> ServerConfig {
        ServerConfig::new(ServerCapabilities::builder().enable_tools().build())
    }

    async fn list_tools(
        &self,
        _request: Option<PaginatedRequestParams>,
        _context: RequestContext<RoleServer>,
    ) -> Result<ListToolsResult, ErrorData> {
        Ok(ListToolsResult::with_all_items(tools()))
    }

    async fn call_tool(
        &self,
        request: CallToolRequestParams,
        _context: RequestContext<RoleServer>,
    ) -> Result<CallToolResponse, ErrorData> {
        let args = request.arguments.unwrap_or_default();
        let view = match request.name.as_ref() {
            "room_status" => View::Status,
            "item_list" => View::ItemList,
            "disagreements" => View::Disagreements,
            "item_show" => {
                let id = args.get("id").and_then(Value::as_str).ok_or_else(|| {
                    ErrorData::invalid_params("item_show needs a string id", None)
                })?;
                View::ItemShow(ItemId(id.into()))
            }
            _ => {
                return Err(ErrorData::new(
                    ErrorCode::METHOD_NOT_FOUND,
                    "unknown tool",
                    None,
                ));
            }
        };
        let expected = usize::from(matches!(view, View::ItemShow(_)));
        if args.len() != expected {
            return Err(ErrorData::invalid_params("unexpected tool arguments", None));
        }
        let result = match read_view(&self.dir, &view) {
            Ok(value) => CallToolResult::success(vec![ContentBlock::text(value.to_string())]),
            Err(error) => {
                CallToolResult::error(vec![ContentBlock::text(one_line(&error.to_string()))])
            }
        };
        Ok(result.into())
    }
}
