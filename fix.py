
                if resp.status_code >= 400:
                    # Some registrars (like OpenProvider) return HTTP 500 with a JSON body for specific
                    # TLD errors (e.g. poison TLDs). Attempt to parse it before blindly retrying.
                    is_poison = False
                    if resp.status_code == 500:
                        try:
                            body = resp.json()
                            if body.get("code") in _DOMAIN_CHECK_POISON_CODES:
                                is_poison = True
                                desc = body.get("desc") or body.get("message") or "unknown"
                                logger.warning("[OPENPROVIDER_SEARCH] HTTP 500 on batch (size %s) with poison code %s - treating as poisoned", len(chunk), body.get("code"))
                                raise _PoisonBatchError(
                                    f"OpenProvider domains/check batch poisoned (code={body.get("code")}): {desc}",
                                    chunk=chunk,
                                )
                        except json.JSONDecodeError:
                            pass
                        except _PoisonBatchError:
                            raise

                    if resp.status_code in (429, 500, 502, 503, 504) and not is_poison:
                        logger.warning(
                            "[OPENPROVIDER_SEARCH] Batch %s attempt %s got HTTP %s, retrying",
                            (idx - total_batches + 1) if idx >= total_batches else (idx + 1), attempt, resp.status_code,
                        )
                        last_err = RuntimeError(
                            _format_http_error("domains/check", resp.status_code, resp.text or "")
                        )
                        await asyncio.sleep(min(2 ** attempt, 8))
                        continue
                    
                    logger.error(
                        "[OPENPROVIDER_SEARCH] Bulk check failed HTTP %s: %s",
                        resp.status_code,
                        (resp.text or "")[:800],
                    )
                    raise RuntimeError(
                        _format_http_error("domains/check", resp.status_code, resp.text or "")
                    )
