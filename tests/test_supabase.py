import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

import app.db.supabase as db_module


@pytest.fixture(autouse=True)
def reset_client():
    db_module._client = None
    db_module._consecutive_failures = 0
    db_module._last_failure_time = 0.0
    yield
    db_module._client = None
    db_module._consecutive_failures = 0
    db_module._last_failure_time = 0.0


class TestGetClient:
    async def test_creates_client_on_first_call(self):
        mock_client = AsyncMock()
        with patch.object(
            db_module, "acreate_client", new_callable=AsyncMock, return_value=mock_client
        ):
            client = await db_module.get_client()
            assert client is mock_client

    async def test_reuses_existing_client(self):
        mock_client = AsyncMock()
        with patch.object(
            db_module, "acreate_client", new_callable=AsyncMock, return_value=mock_client
        ) as mock_create:
            await db_module.get_client()
            await db_module.get_client()
            mock_create.assert_awaited_once()

    async def test_propagates_init_error(self):
        with patch.object(
            db_module,
            "acreate_client",
            new_callable=AsyncMock,
            side_effect=Exception("connection refused"),
        ):
            with pytest.raises(Exception, match="connection refused"):
                await db_module.get_client()


class TestSaveDescription:
    @pytest.fixture
    def mock_client(self):
        client = MagicMock()
        result = MagicMock()
        result.data = [{"id": 1, "cog_image_id": "test-img"}]
        client.table.return_value.upsert.return_value.execute = AsyncMock(return_value=result)
        return client

    async def test_save_success(self, mock_client):
        with patch.object(
            db_module, "get_client", new_callable=AsyncMock, return_value=mock_client
        ):
            result = await db_module.save_description(
                cog_image_id="test-img",
                coordinates=[127.0, 37.0],
                captured_at="2024-01-01",
                location={
                    "country": "KR",
                    "region": "Seoul",
                    "city": "Gangnam",
                    "country_code": "KR",
                    "place_name": "Seoul",
                },
                land_cover={"classes": [{"name": "urban"}], "summary": "urban area"},
                description="test description",
                context={"events": [], "summary": "no events"},
            )
            assert result is True

    async def test_save_without_optional_fields(self, mock_client):
        with patch.object(
            db_module, "get_client", new_callable=AsyncMock, return_value=mock_client
        ):
            result = await db_module.save_description(
                cog_image_id="test-img",
                coordinates=[127.0, 37.0],
                captured_at=None,
                location=None,
                land_cover=None,
                description=None,
                context=None,
            )
            assert result is True

    async def test_save_returns_false_on_error(self):
        mock_client = MagicMock()
        mock_client.table.return_value.upsert.return_value.execute = AsyncMock(
            side_effect=Exception("db error")
        )
        with patch.object(
            db_module, "get_client", new_callable=AsyncMock, return_value=mock_client
        ):
            result = await db_module.save_description(
                cog_image_id="test-img",
                coordinates=[127.0, 37.0],
                captured_at=None,
                location=None,
                land_cover=None,
                description="test",
                context=None,
            )
            assert result is False

    async def test_save_returns_true_on_empty_result(self):
        mock_client = MagicMock()
        result = MagicMock()
        result.data = []
        mock_client.table.return_value.upsert.return_value.execute = AsyncMock(return_value=result)
        with patch.object(
            db_module, "get_client", new_callable=AsyncMock, return_value=mock_client
        ):
            result = await db_module.save_description(
                cog_image_id="test-img",
                coordinates=[127.0, 37.0],
                captured_at=None,
                location=None,
                land_cover=None,
                description="test",
                context=None,
            )
            assert result is True

    async def test_save_timeout(self):
        mock_client = MagicMock()

        async def slow_execute():
            await asyncio.sleep(20)

        mock_client.table.return_value.upsert.return_value.execute = slow_execute
        with patch.object(
            db_module, "get_client", new_callable=AsyncMock, return_value=mock_client
        ):
            with patch.object(db_module.settings, "supabase_save_timeout", 0.1):
                result = await db_module.save_description(
                    cog_image_id="test-img",
                    coordinates=[127.0, 37.0],
                    captured_at=None,
                    location=None,
                    land_cover=None,
                    description="test",
                    context=None,
                )
                assert result is False


class TestGetDescription:
    async def test_get_found(self):
        mock_client = MagicMock()
        result = MagicMock()
        result.data = [{"cog_image_id": "img-1", "description": "test"}]
        query_chain = mock_client.table.return_value.select.return_value
        query_chain.eq.return_value.limit.return_value.execute = AsyncMock(return_value=result)
        with patch.object(
            db_module, "get_client", new_callable=AsyncMock, return_value=mock_client
        ):
            row = await db_module.get_description("img-1")
            assert row == {"cog_image_id": "img-1", "description": "test"}

    async def test_get_not_found(self):
        mock_client = MagicMock()
        result = MagicMock()
        result.data = []
        query_chain = mock_client.table.return_value.select.return_value
        query_chain.eq.return_value.limit.return_value.execute = AsyncMock(return_value=result)
        with patch.object(
            db_module, "get_client", new_callable=AsyncMock, return_value=mock_client
        ):
            row = await db_module.get_description("nonexistent")
            assert row is None

    async def test_get_returns_none_on_error(self):
        mock_client = MagicMock()
        query_chain = mock_client.table.return_value.select.return_value
        query_chain.eq.return_value.limit.return_value.execute = AsyncMock(
            side_effect=Exception("network error")
        )
        with patch.object(
            db_module, "get_client", new_callable=AsyncMock, return_value=mock_client
        ):
            row = await db_module.get_description("img-1")
            assert row is None


class TestDeleteDescription:
    async def test_delete_success(self):
        mock_client = MagicMock()
        result = MagicMock()
        result.data = [{"cog_image_id": "img-1"}]
        mock_client.table.return_value.delete.return_value.eq.return_value.execute = AsyncMock(
            return_value=result
        )
        with patch.object(
            db_module, "get_client", new_callable=AsyncMock, return_value=mock_client
        ):
            assert await db_module.delete_description("img-1") is True

    async def test_delete_not_found(self):
        mock_client = MagicMock()
        result = MagicMock()
        result.data = []
        mock_client.table.return_value.delete.return_value.eq.return_value.execute = AsyncMock(
            return_value=result
        )
        with patch.object(
            db_module, "get_client", new_callable=AsyncMock, return_value=mock_client
        ):
            assert await db_module.delete_description("nonexistent") is False

    async def test_delete_returns_false_on_error(self):
        mock_client = MagicMock()
        mock_client.table.return_value.delete.return_value.eq.return_value.execute = AsyncMock(
            side_effect=Exception("db error")
        )
        with patch.object(
            db_module, "get_client", new_callable=AsyncMock, return_value=mock_client
        ):
            assert await db_module.delete_description("img-1") is False


@pytest.mark.asyncio
class TestListDescriptions:
    async def test_list_returns_items(self):
        mock_client = MagicMock()
        result = MagicMock()
        result.data = [{"cog_image_id": "img-1"}, {"cog_image_id": "img-2"}]
        result.count = 2
        query = mock_client.table.return_value.select.return_value
        query.order.return_value.range.return_value.execute = AsyncMock(return_value=result)
        with patch.object(
            db_module, "get_client", new_callable=AsyncMock, return_value=mock_client
        ):
            res = await db_module.list_descriptions(offset=0, limit=20)
            assert res["total"] == 2
            assert len(res["items"]) == 2

    async def test_list_with_date_filters(self):
        mock_client = MagicMock()
        result = MagicMock()
        result.data = [{"cog_image_id": "img-1"}]
        result.count = 1
        query = mock_client.table.return_value.select.return_value
        query.gte.return_value.lte.return_value.order.return_value.range.return_value.execute = (
            AsyncMock(return_value=result)
        )
        with patch.object(
            db_module, "get_client", new_callable=AsyncMock, return_value=mock_client
        ):
            res = await db_module.list_descriptions(
                created_after="2025-01-01", created_before="2025-12-31"
            )
            assert res["total"] == 1

    async def test_list_returns_empty_on_error(self):
        mock_client = MagicMock()
        query = mock_client.table.return_value.select.return_value
        query.order.return_value.range.return_value.execute = AsyncMock(
            side_effect=Exception("network error")
        )
        with patch.object(
            db_module, "get_client", new_callable=AsyncMock, return_value=mock_client
        ):
            res = await db_module.list_descriptions()
            assert res["items"] == []
            assert res["total"] == 0


class TestClientReinitialization:
    """Tests for #236: Supabase client reconnection on failure."""

    async def test_client_reset_on_init_failure(self):
        """get_client() should reset and re-raise on connection failure."""
        with patch.object(
            db_module,
            "acreate_client",
            new_callable=AsyncMock,
            side_effect=Exception("connection refused"),
        ):
            with pytest.raises(Exception, match="connection refused"):
                await db_module.get_client()
            assert db_module._client is None
            assert db_module._consecutive_failures == 1

    async def test_client_recreated_after_reset(self):
        """After a reset, get_client() should create a new client."""
        mock_client = AsyncMock()
        call_count = 0

        async def create_side_effect(*args, **kwargs):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                raise Exception("temporary failure")
            return mock_client

        with patch.object(
            db_module, "acreate_client", new_callable=AsyncMock, side_effect=create_side_effect
        ):
            with pytest.raises(Exception, match="temporary failure"):
                await db_module.get_client()
            # Reset backoff for test
            db_module._last_failure_time = 0.0
            client = await db_module.get_client()
            assert client is mock_client
            assert db_module._consecutive_failures == 0

    async def test_backoff_blocks_reconnect(self):
        """During backoff period, get_client() should raise ConnectionError."""
        import time

        db_module._consecutive_failures = 3
        db_module._last_failure_time = time.monotonic()
        with pytest.raises(ConnectionError, match="backoff"):
            await db_module.get_client()

    async def test_save_resets_client_on_error(self):
        """save_description should reset client on failure."""
        mock_client = MagicMock()
        mock_client.table.return_value.upsert.return_value.execute = AsyncMock(
            side_effect=Exception("connection lost")
        )
        db_module._client = mock_client
        result = await db_module.save_description(
            cog_image_id="test",
            coordinates=[127.0, 37.0],
            captured_at=None,
            location=None,
            land_cover=None,
            description="test",
            context=None,
        )
        assert result is False
        assert db_module._client is None

    async def test_ping_resets_client_on_error(self):
        """ping should reset client on failure."""
        mock_client = MagicMock()
        mock_client.table.return_value.select.return_value.limit.return_value.execute = AsyncMock(
            side_effect=Exception("connection lost")
        )
        db_module._client = mock_client
        result = await db_module.ping()
        assert result is False
        assert db_module._client is None

    async def test_ping_timeout_returns_false(self):
        """#251: ping should return False on timeout without resetting client."""
        mock_client = MagicMock()

        async def slow_execute():
            await asyncio.sleep(20)

        mock_client.table.return_value.select.return_value.limit.return_value.execute = slow_execute
        db_module._client = mock_client
        with patch.object(db_module.settings, "timeout_supabase_ping", 0.1):
            result = await db_module.ping()
        assert result is False
        # Client should NOT be reset on timeout (it's not a connection error)
        assert db_module._client is mock_client
