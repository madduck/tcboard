from abc import ABC, abstractmethod
from typing import Any, ClassVar, Self, cast


class ABCWithRegistry(ABC):
    _registry: ClassVar[dict[str, type["ABCWithRegistry"]]] = {}

    @classmethod
    @abstractmethod
    def model_validate(cls, obj: Any) -> Self: ...

    @classmethod
    def _model_name(cls) -> str:
        return ".".join((cls.__module__, cls.__qualname__))

    @property
    def modelid(self) -> str:
        return self._model_name()

    def __init_subclass__(cls, **kwargs: Any) -> None:
        super().__init_subclass__(**kwargs)
        name = cls._model_name()
        cls._registry[name] = cls

    @classmethod
    def make_model_instance(cls, modelid: str, data: Any) -> Self:
        try:
            modelcls = cast(Self, cls._registry[modelid])
            return modelcls.model_validate(data)

        except KeyError as exc:
            raise TypeError(f"Model specialisation not known: {modelid}") from exc
