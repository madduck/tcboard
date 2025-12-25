# needed < 3.14 so that annotations aren't evaluated
from __future__ import annotations

from collections.abc import MutableMapping
from typing import Any, ClassVar, Self, cast

from pydantic import (
    BaseModel,
    SerializerFunctionWrapHandler,
    ValidatorFunctionWrapHandler,
    model_serializer,
    model_validator,
)


class ModelABC(BaseModel):
    _registry: ClassVar[dict[str, type[ModelABC]]] = {}

    @classmethod
    def _model_name(cls) -> str:
        return ".".join((cls.__module__, cls.__qualname__))

    def __init_subclass__(cls, **kwargs: Any) -> None:
        super().__init_subclass__(**kwargs)
        name = cls._model_name()
        cls._registry[name] = cls

    @property
    def modelid(self) -> str:
        return self._model_name()

    @model_serializer(mode="wrap")
    def _add_modelid(self, handler: SerializerFunctionWrapHandler) -> dict[str, Any]:
        ret: dict[str, Any] = handler(self)
        ret["_modelid"] = self.modelid
        return ret

    @model_validator(mode="wrap")
    @classmethod
    def _make_from_modelid_if_present(
        cls, data: dict[str, Any], handler: ValidatorFunctionWrapHandler
    ) -> Self:
        if isinstance(data, MutableMapping):
            modelid = data.pop("_modelid", None)

            if modelid is not None:
                return cls.make_model_instance(data, modelid=modelid)

        return cast(Self, handler(data))

    @classmethod
    def _get_model_class(cls, *, modelid: str | None = None) -> type[Self]:
        modelid = modelid if modelid is not None else cls._model_name()
        try:
            return cast(type[Self], cls._registry[modelid])

        except KeyError as exc:
            raise TypeError(f"Model specialisation not known: {modelid}") from exc

    @classmethod
    def make_model_instance(cls, data: Any, *, modelid: str | None = None) -> Self:
        return cls._get_model_class(modelid=modelid).model_validate(data)

    @classmethod
    def make_model_instance_json(cls, json: str, *, modelid: str | None = None) -> Self:
        return cls._get_model_class(modelid=modelid).model_validate_json(json)
